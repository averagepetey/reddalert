"""Tests for Discord OAuth2 endpoints."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles as sa_compiles
from sqlalchemy.orm import sessionmaker

from app.api.auth import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.clients import Client
from app.models.webhooks import WebhookConfig

# ---------------------------------------------------------------------------
# SQLite ARRAY workaround — store arrays as JSON text
# ---------------------------------------------------------------------------

@sa_compiles(ARRAY, "sqlite")
def _compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"


_orig_array_bind = ARRAY.bind_processor
_orig_array_result = ARRAY.result_processor


def _array_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return json.dumps(value)
            return None
        return process
    if _orig_array_bind:
        return _orig_array_bind(self, dialect)
    return None


def _array_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                if isinstance(value, str):
                    return json.loads(value)
                return value
            return None
        return process
    if _orig_array_result:
        return _orig_array_result(self, dialect, coltype)
    return None


ARRAY.bind_processor = _array_bind_processor
ARRAY.result_processor = _array_result_processor

# ---------------------------------------------------------------------------
# Test database setup (SQLite in-memory, shared connection)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_db():
    """Create tables, provide shared connection, drop after test."""
    connection = engine.connect()
    transaction = connection.begin()

    Base.metadata.create_all(bind=connection)

    TestSession = sessionmaker(bind=connection)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestSession

    transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()


@pytest.fixture
def db_session(setup_db):
    """Get a session on the shared connection."""
    TestSession = setup_db
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def test_client_record(db_session):
    """Create a client with a known password for authenticated requests."""
    raw_password = "test-password-12345"
    c = Client(
        id=uuid.uuid4(),
        email="discord-test@example.com",
        password_hash=hash_password(raw_password),
        polling_interval=60,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    token = create_access_token(str(c.id))
    return c, token


@pytest.fixture
def auth_header(test_client_record):
    """Return authorization header dict for the test client."""
    _, token = test_client_record
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /api/discord/auth-url
# ---------------------------------------------------------------------------

@patch("app.api.discord.DISCORD_CLIENT_ID", "test-client-id-123")
@patch("app.api.discord.DISCORD_REDIRECT_URI", "http://localhost:3000/discord/callback")
def test_get_auth_url_returns_url_and_state(test_client, auth_header):
    resp = test_client.get("/api/discord/auth-url", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "state" in data
    assert "test-client-id-123" in data["auth_url"]
    assert "webhook.incoming" in data["auth_url"]
    assert "discord.com" in data["auth_url"]
    # State should be a non-empty string
    assert len(data["state"]) > 0


def test_get_auth_url_requires_auth(test_client):
    resp = test_client.get("/api/discord/auth-url")
    assert resp.status_code == 401


@patch("app.api.discord.DISCORD_CLIENT_ID", "")
def test_get_auth_url_not_configured(test_client, auth_header):
    resp = test_client.get("/api/discord/auth-url", headers=auth_header)
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/discord/callback
# ---------------------------------------------------------------------------

@patch("app.api.discord.DISCORD_CLIENT_ID", "test-id")
@patch("app.api.discord.DISCORD_CLIENT_SECRET", "test-secret")
@patch("app.api.discord.httpx.Client")
def test_callback_exchanges_code_and_creates_webhook(
    mock_httpx_client_cls, test_client, auth_header, db_session, test_client_record
):
    """Successful callback: Discord returns webhook, we save it."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "abc123",
        "webhook": {
            "url": "https://discord.com/api/webhooks/111/xyz",
            "name": "reddalert",
            "channel_id": "999",
            "guild_id": "888",
            "id": "111",
        },
    }

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.post.return_value = mock_response
    mock_httpx_client_cls.return_value = mock_http_instance

    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "discord-auth-code", "state": "random-state"},
        headers=auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://discord.com/api/webhooks/111/xyz"
    assert data["is_primary"] is True

    # Verify webhook was persisted in DB
    client_obj, _ = test_client_record
    wh = db_session.query(WebhookConfig).filter(
        WebhookConfig.client_id == client_obj.id
    ).first()
    assert wh is not None
    assert wh.url == "https://discord.com/api/webhooks/111/xyz"


def test_callback_requires_auth(test_client):
    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "some-code", "state": "some-state"},
    )
    assert resp.status_code == 401


def test_callback_empty_code_rejected(test_client, auth_header):
    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 422


@patch("app.api.discord.DISCORD_CLIENT_ID", "test-id")
@patch("app.api.discord.DISCORD_CLIENT_SECRET", "test-secret")
@patch("app.api.discord.httpx.Client")
def test_callback_discord_error_returns_400(
    mock_httpx_client_cls, test_client, auth_header
):
    """Discord returns non-200 (e.g. 401 for bad code) -> our 400."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.post.return_value = mock_response
    mock_httpx_client_cls.return_value = mock_http_instance

    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "bad-code", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 400
    assert "rejected" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()


@patch("app.api.discord.DISCORD_CLIENT_ID", "test-id")
@patch("app.api.discord.DISCORD_CLIENT_SECRET", "test-secret")
@patch("app.api.discord.httpx.Client")
def test_callback_discord_unreachable_returns_502(
    mock_httpx_client_cls, test_client, auth_header
):
    """Network error when calling Discord -> 502."""
    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.post.side_effect = httpx.ConnectError("Connection refused")
    mock_httpx_client_cls.return_value = mock_http_instance

    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "some-code", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 502
    assert "could not reach discord" in resp.json()["detail"].lower()


@patch("app.api.discord.DISCORD_CLIENT_ID", "test-id")
@patch("app.api.discord.DISCORD_CLIENT_SECRET", "test-secret")
@patch("app.api.discord.httpx.Client")
def test_callback_missing_webhook_in_response(
    mock_httpx_client_cls, test_client, auth_header
):
    """Discord returns 200 but no webhook object -> 502."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "abc123",
        # No "webhook" key
    }

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.post.return_value = mock_response
    mock_httpx_client_cls.return_value = mock_http_instance

    resp = test_client.post(
        "/api/discord/callback",
        json={"code": "some-code", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 502
    assert "webhook" in resp.json()["detail"].lower()
