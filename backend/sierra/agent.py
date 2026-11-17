import hashlib
import json
import re
import threading
import time

from fastapi import HTTPException
from sqlalchemy import select

from .grounding import verify_results
from .db import aware, utcnow
from .memory import compact, context_snapshot
from .models import ChatRun, Conversation, Message, Product
from .planner import plan_message
from .recommendation import ProductSearch
from .schemas import Reply, Result
from .security import is_injection
from .tools import Tools


class Agent:
    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings
        self.policies = json.loads((settings.data_dir / "policies.json").read_text())
        with sessions() as db:
            products = [{"sku": p.sku, "name": p.name, "description": p.description, "tags": p.tags, "inventory": p.inventory}
                        for p in db.scalars(select(Product))]
        self.search = ProductSearch(products)
        # Bounded striped locks cover SQLite demo requests; PostgreSQL also locks conversation/customer rows.
        self.locks = [threading.RLock() for _ in range(128)]

    def run(self, conversation_id, request, received_at):
        start = time.monotonic()
        lock = self.locks[int(hashlib.sha256(conversation_id.encode()).hexdigest(), 16) % len(self.locks)]
        if not lock.acquire(timeout=1):
            raise HTTPException(503, "This conversation is busy. Retry with the same request_id.")
        try:
            with self.sessions.begin() as db:
                conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
                if conv is None or aware(conv.expires_at) <= utcnow():
                    raise HTTPException(401, "Session expired. Start a new conversation.")
                fingerprint = hashlib.sha256(request.message.encode()).hexdigest()
                previous = db.scalar(select(ChatRun).where(ChatRun.conversation_id == conv.id, ChatRun.request_id == request.request_id))
                if previous:
                    if previous.message_hash != fingerprint:
                        raise HTTPException(409, "request_id was already used for a different message")
                    return Reply.model_validate(previous.response)
                state = dict(conv.state)
                if re.search(r"[\u4e00-\u9fff]", request.message):
                    state["language"] = "zh"
                elif re.search(r"[a-z]{3}", request.message, re.I) and "@" not in request.message:
                    state["language"] = "en"
                conv.state = state
                tools = Tools(db, conv, request.request_id, received_at, self.settings, self.search, self.policies)
                if is_injection(request.message):
                    results = [Result(workflow="safety", status="refused", text=tools.say(
                        "我可以帮助查询订单、推荐商品和处理早鸟优惠。客户数据和系统权限不能通过对话指令更改。🏔️",
                        "I can help with Sierra orders, products and Early Risers. Customer-data access and system permissions cannot be changed through chat instructions. 🏔️"))]
                    planner = "safety"
                elif re.search(r"https?://", request.message, re.I):
                    results = [Result(workflow="safety", status="url_not_opened", text=tools.say(
                        "我不会打开外部链接。请直接描述订单或商品问题，我会使用 Sierra 的数据协助你。",
                        "I don't open external links. Describe your order or product question and I'll use Sierra's records to help."))]
                    planner = "safety"
                else:
                    plan, planner = plan_message(request.message, context_snapshot(db, conv), self.settings)
                    self.check_deadline(start)
                    results = []
                    # Model-provided query text may assist search; never supplies identity or authorization.
                    for intent in sorted(set(plan.intents), key=lambda i: ["lookup", "cancel", "return", "recommend", "coupon", "policy", "handoff", "greeting", "scope"].index(i)):
                        self.check_deadline(start)
                        if intent == "lookup":
                            result = tools.lookup(request.message)
                        elif intent in {"cancel", "return"}:
                            result = tools.order_action(intent, request.message)
                        elif intent == "recommend":
                            result = tools.recommend(plan.search_query or request.message)
                        elif intent == "coupon":
                            result = tools.coupon(request.message)
                        elif intent == "handoff":
                            result = tools.handoff("customer_request", tools.say("客户明确请求人工协助。", "Customer explicitly requested human support."))
                        elif intent == "policy":
                            result = tools.policy_answer(request.message)
                        else:
                            result = Result(workflow=intent, status="information", text=tools.say(
                                "你好，我是 Sierra 的冒险助手。可以帮你查订单、推荐装备、申请取消或退货，以及领取早鸟优惠。🏔️",
                                "Welcome to Sierra. I can track orders, find gear, help with cancellation or return requests, and check Early Risers offers. Onward to your next adventure! 🏔️"))
                        results.append(result)
                # Revalidate after all tools; refresh earlier order evidence if a compound request changed it.
                self.refresh_order_results(db, tools, results)
                verify_results(db, conv, tools.state, results, self.policies)
                conv.state = tools.state
                text = "\n\n".join(result.text for result in results)
                db.add_all([Message(conversation_id=conv.id, role="user", content=request.message),
                            Message(conversation_id=conv.id, role="assistant", content=text)])
                memory = compact(db, conv, self.settings.memory_char_budget)
                self.check_deadline(start)
                reply = Reply(request_id=request.request_id, text=text, results=results, grounded=True,
                              latency_ms=round((time.monotonic() - start) * 1000, 1), planner=planner, memory=memory)
                db.add(ChatRun(conversation_id=conv.id, request_id=request.request_id,
                               message_hash=fingerprint, response=reply.model_dump(mode="json")))
                # Context manager commits before returning to the HTTP/streaming layer.
            return reply
        finally:
            lock.release()

    def refresh_order_results(self, db, tools, results):
        from .models import Order
        for result in results:
            for index, evidence in enumerate(result.evidence):
                if evidence.kind == "order":
                    order = db.get(Order, evidence.facts["order_number"])
                    changed = evidence.facts["version"] != order.version
                    result.evidence[index] = tools.order_evidence(order)
                    if changed and result.workflow == "lookup" and result.status == "ok":
                        result.data = tools.order_view(order)
                        result.text = tools.say(f"订单 {order.number} 当前状态：{result.data['status_label']}。",
                                                f"Order {order.number} is now {result.data['status_label']}.")

    def check_deadline(self, started):
        if time.monotonic() - started > self.settings.request_timeout_seconds:
            raise HTTPException(503, "The request deadline was exceeded; changes were rolled back. Retry with the same request_id.")
