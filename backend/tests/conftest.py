from datetime import datetime, timezone
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from sierra.config import Settings
from sierra.main import create_app


@pytest.fixture
def app(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    external = os.getenv("TEST_DATABASE_URL")
    if external:
        import psycopg
        from psycopg import sql
        parts = urlsplit(external.replace("postgresql+psycopg://", "postgresql://"))
        maintenance = urlunsplit(parts._replace(path="/postgres"))
        name = "sierra_test_" + uuid.uuid4().hex[:12]
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        database_url = urlunsplit(parts._replace(scheme="postgresql+psycopg", path="/" + name))
    settings = Settings(database_url=database_url, demo_mode=True,
                        anthropic_api_key="", coupon_secret="a-private-test-key-that-is-not-used-outside-tests",
                        memory_char_budget=2400)
    application = create_app(settings)
    application.state.clock = lambda: datetime(2026, 11, 17, 16, 30, tzinfo=timezone.utc)
    application.state.limiter.limit = 10000
    yield application
    application.state.sessions.kw["bind"].dispose()
    if external:
        with psycopg.connect(maintenance, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        session.get("/api/session")
        yield session


def login(client, email="explorer01@example.com"):
    response = client.post("/api/auth/demo", json={"email": email, "password": "trail-demo"})
    assert response.status_code == 200
    return response.json()


def chat(client, message, request_id=None):
    import uuid
    response = client.post("/api/chat", json={"message": message, "request_id": request_id or str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    return response.json()
