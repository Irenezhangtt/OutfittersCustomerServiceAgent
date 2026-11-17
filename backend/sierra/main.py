import asyncio
import json
import mimetypes
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .agent import Agent
from .config import Settings
from .db import aware, make_database, seed_database, utcnow
from .grounding import GroundingError
from .models import Conversation, Customer, Message, Ticket
from .schemas import ChatRequest, LoginRequest
from .security import COOKIE_NAME, RateLimiter, new_token, token_hash


def create_app(settings=None):
    settings = settings or Settings()
    settings.validate_runtime()
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(seed_database, engine, sessions, settings)
        app.state.agent = await run_in_threadpool(Agent, sessions, settings)
        if settings.frontend_dir.exists():
            # Small immutable UI bundle: load once, avoid platform-specific file-send behavior.
            def load_assets():
                return {p.relative_to(settings.frontend_dir).as_posix(): p.read_bytes()
                        for p in settings.frontend_dir.rglob("*") if p.is_file()}
            app.state.assets = await run_in_threadpool(load_assets)
        yield
        engine.dispose()

    app = FastAPI(title="Sierra Outfitters Customer Service", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.sessions = settings, sessions
    app.state.clock = utcnow  # Dependency injection in tests only; no client-controlled time endpoint.
    app.state.limiter = RateLimiter()
    app.state.latencies = deque(maxlen=1000)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        # Capture trusted receipt time before classification, model calls or queueing.
        request.state.received_at = app.state.clock()
        request.state.started = time.monotonic()
        origin = request.headers.get("origin")
        allowed = {value.strip() for value in settings.allowed_origins.split(",")}
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if origin and origin not in allowed:
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are not allowed"}, status_code=403)
            if request.url.path.startswith("/api/"):
                try:
                    app.state.limiter.check(request.client.host if request.client else "unknown")
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if length > 16384:
                return JSONResponse({"detail": "Request is too large"}, status_code=413)
            # Enforce the same limit for chunked requests or inaccurate length headers.
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16384:
                    return JSONResponse({"detail": "Request is too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(_request, _exc):
        return JSONResponse({"detail": "Storage is temporarily unavailable. No successful operation is confirmed. Retry using the same request_id."}, status_code=503)

    @app.exception_handler(GroundingError)
    async def unsupported(_request, _exc):
        return JSONResponse({"detail": "The result could not be verified. Changes were rolled back. Please retry or request human support."}, status_code=503)

    def set_cookie(response, token):
        response.set_cookie(COOKIE_NAME, token, max_age=settings.session_hours * 3600,
                            httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")

    def current_session(request):
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or len(token) > 100:
            raise HTTPException(401, "Start a session first")
        with sessions() as db:
            conv = db.scalar(select(Conversation).where(Conversation.token_hash == token_hash(token)))
            if not conv or aware(conv.expires_at) <= utcnow():
                raise HTTPException(401, "Session expired. Start a new session.")
            return conv

    def make_session(response, customer_id=None):
        token = new_token()
        with sessions.begin() as db:
            conv = Conversation(token_hash=token_hash(token), customer_id=customer_id, state={}, summary={},
                                expires_at=utcnow() + timedelta(hours=settings.session_hours))
            db.add(conv)
            db.flush()
        set_cookie(response, token)
        return conv

    def session_view(conv):
        with sessions() as db:
            customer = db.get(Customer, conv.customer_id) if conv.customer_id else None
            rows = list(db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(12)))
            return {"authenticated": customer is not None, "customer": {"name": customer.name, "email": customer.email} if customer else None,
                    "demo_mode": settings.demo_mode, "planner": "llm-assisted" if settings.anthropic_api_key else "local",
                    "messages": [{"role": m.role, "content": m.content} for m in reversed(rows)],
                    "current_order": conv.state.get("current_order"), "summary_compacted": conv.summary.get("compacted_messages", 0)}

    @app.get("/api/session")
    def get_session(request: Request, response: Response):
        try:
            conv = current_session(request)
        except HTTPException:
            conv = make_session(response)
        return session_view(conv)

    @app.get("/api/demo/accounts")
    def demo_accounts():
        if not settings.demo_mode:
            raise HTTPException(404, "Demo mode is disabled")
        with sessions() as db:
            return [{"name": c.name, "email": c.email} for c in db.scalars(select(Customer).order_by(Customer.email))]

    @app.post("/api/auth/demo")
    def demo_login(body: LoginRequest, request: Request, response: Response):
        if not settings.demo_mode:
            raise HTTPException(404, "Demo mode is disabled")
        if not secrets.compare_digest(body.password.encode(), settings.demo_password.encode()):
            raise HTTPException(401, "Invalid demo credentials")
        with sessions() as db:
            customer = db.scalar(select(Customer).where(Customer.email == body.email.strip().lower()))
            if not customer:
                raise HTTPException(401, "Invalid demo credentials")
        try:
            previous = current_session(request)
            with sessions.begin() as db:
                old = db.get(Conversation, previous.id)
                old.token_hash = token_hash(new_token())
                old.expires_at = utcnow()
        except HTTPException:
            pass
        return session_view(make_session(response, customer.id))

    @app.post("/api/session/reset")
    def reset_session(request: Request, response: Response):
        previous = current_session(request)
        with sessions.begin() as db:
            old = db.get(Conversation, previous.id)
            old.token_hash = token_hash(new_token())
            old.expires_at = utcnow()
        return session_view(make_session(response, previous.customer_id))

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        previous = current_session(request)
        with sessions.begin() as db:
            old = db.get(Conversation, previous.id)
            old.token_hash = token_hash(new_token())
            old.expires_at = utcnow()
        return session_view(make_session(response))

    def run_chat(conv_id, body, received_at):
        started = time.monotonic()
        result = app.state.agent.run(conv_id, body, received_at)
        app.state.latencies.append(round((time.monotonic() - started) * 1000, 1))
        return result

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        conv = await run_in_threadpool(current_session, request)
        return await run_in_threadpool(run_chat, conv.id, body, request.state.received_at)

    @app.post("/api/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request):
        conv = await run_in_threadpool(current_session, request)

        async def events():
            yield json.dumps({"type": "phase", "phase": "checking", "detail": "Checking records and permissions"}) + "\n"
            task = asyncio.create_task(run_in_threadpool(run_chat, conv.id, body, request.state.received_at))
            try:
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=1)
                    if not done:
                        yield json.dumps({"type": "phase", "phase": "working", "detail": "Still checking your request"}) + "\n"
                result = await task
                yield json.dumps({"type": "result", "data": result.model_dump(mode="json")}, ensure_ascii=False) + "\n"
            except HTTPException as exc:
                yield json.dumps({"type": "error", "detail": exc.detail, "status": exc.status_code, "request_id": body.request_id}) + "\n"
            except (SQLAlchemyError, GroundingError, RuntimeError):
                yield json.dumps({"type": "error", "detail": "Unable to confirm a successful operation. Retry with the same request_id.", "status": 503, "request_id": body.request_id}) + "\n"
            finally:
                # A disconnect does not cancel a committed write; retry is idempotent.
                if not task.done():
                    try:
                        await asyncio.shield(task)
                    except (HTTPException, SQLAlchemyError, GroundingError, RuntimeError):
                        pass

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/tickets")
    def tickets(request: Request):
        conv = current_session(request)
        with sessions() as db:
            return [{"reference": t.reference, "status": t.status, "reason": t.reason, "created_at": t.created_at.isoformat()}
                    for t in db.scalars(select(Ticket).where(Ticket.conversation_id == conv.id).order_by(Ticket.created_at.desc()).limit(30))]

    @app.get("/api/health")
    def health():
        with sessions() as db:
            db.execute(text("SELECT 1"))
        times = sorted(app.state.latencies)
        return {"status": "ok", "database": "postgresql" if engine.dialect.name == "postgresql" else "sqlite",
                "demo_mode": settings.demo_mode, "planner": "llm-assisted" if settings.anthropic_api_key else "local",
                "pacific_time": app.state.clock().astimezone(ZoneInfo("America/Los_Angeles")).isoformat(),
                "samples": len(times), "p95_ms": times[min(len(times) - 1, int(len(times) * .95))] if times else None}

    if settings.frontend_dir.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def static_asset(path: str):
            key = path or "index.html"
            asset = app.state.assets.get(key)
            if asset is None:
                raise HTTPException(404, "Not found")
            media = mimetypes.guess_type(key)[0] or "application/octet-stream"
            return Response(asset, media_type=media, headers={"Cache-Control": "public, max-age=31536000, immutable" if key.startswith("assets/") else "no-cache"})
    else:
        @app.get("/")
        def root():
            return {"message": "Sierra API is running. Build frontend with npm --prefix frontend run build, then restart, or run the Vite dev server.", "docs": "/docs"}
    return app


app = create_app()
