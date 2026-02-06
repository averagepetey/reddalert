"""Tests for Discord bot-based endpoints."""
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
# Mock helper for bot-based Discord API calls
# ---------------------------------------------------------------------------

def _mock_httpx_for_bot(
    channel_status: int = 200,
    channel_json: Optional[dict] = None,
    webhook_status: int = 200,
    webhook_json: Optional[dict] = None,
    channel_side_effect: Optional[Exception] = None,
    webhook_side_effect: Optional[Exception] = None,
):
    """Return a mock httpx.Client class that routes based on URL.

    - POST to /guilds/.../channels -> channel response
    - POST to /channels/.../webhooks -> webhook response
    """
    if channel_json is None:
        channel_json = {"id": "777888999", "name": "reddalert-alerts"}
    if webhook_json is None:
        webhook_json = {
            "id": "111222333",
            "token": "webhook-token-abc",
            "name": "Reddalert",
            "channel_id": "777888999",
        }

    def _make_response(status_code, json_data):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.text = json.dumps(json_data)
        return resp

    def _side_effect_post(url, **kwargs):
        if "/guilds/" in url and "/channels" in url:
            if channel_side_effect:
                raise channel_side_effect
            return _make_response(channel_status, channel_json)
        if "/channels/" in url and "/webhooks" in url:
            if webhook_side_effect:
                raise webhook_side_effect
            return _make_response(webhook_status, webhook_json)
        return _make_response(404, {"message": "Unknown URL"})

    mock_http_instance = MagicMock()
    mock_http_instance.__enter__ = MagicMock(return_value=mock_http_instance)
    mock_http_instance.__exit__ = MagicMock(return_value=False)
    mock_http_instance.post.side_effect = _side_effect_post

    mock_cls = MagicMock(return_value=mock_http_instance)
    return mock_cls


# Need Optional for type hints in Python 3.9
from typing import Optional


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
    assert "scope=bot" in data["auth_url"]
    assert "permissions=536870928" in data["auth_url"]
    # Bot flow should NOT have response_type
    assert "response_type" not in data["auth_url"]
    assert "discord.com" in data["auth_url"]
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

@patch("app.api.discord.DISCORD_BOT_TOKEN", "test-bot-token")
@patch("app.api.discord.httpx.Client")
def test_callback_creates_channel_webhook_and_saves(
    mock_httpx_client_cls, test_client, auth_header, db_session, test_client_record
):
    """Happy path: bot creates channel, creates webhook, saves to DB."""
    mock_httpx_client_cls.side_effect = None
    mock_httpx_client_cls.return_value = _mock_httpx_for_bot().return_value

    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "random-state"},
        headers=auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://discord.com/api/webhooks/111222333/webhook-token-abc"
    assert data["is_primary"] is True

    # Verify webhook was persisted in DB
    client_obj, _ = test_client_record
    wh = db_session.query(WebhookConfig).filter(
        WebhookConfig.client_id == client_obj.id
    ).first()
    assert wh is not None
    assert wh.url == "https://discord.com/api/webhooks/111222333/webhook-token-abc"


def test_callback_requires_auth(test_client):
    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "some-state"},
    )
    assert resp.status_code == 401


def test_callback_empty_guild_id_rejected(test_client, auth_header):
    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_callback_non_numeric_guild_id_rejected(test_client, auth_header):
    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "not-a-number", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 422


@patch("app.api.discord.DISCORD_BOT_TOKEN", "test-bot-token")
@patch("app.api.discord.httpx.Client")
def test_callback_channel_creation_403_returns_403(
    mock_httpx_client_cls, test_client, auth_header
):
    """Bot lacks permission to create channels -> 403."""
    mock_httpx_client_cls.side_effect = None
    mock_httpx_client_cls.return_value = _mock_httpx_for_bot(
        channel_status=403,
        channel_json={"message": "Missing Permissions"},
    ).return_value

    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 403
    assert "permission" in resp.json()["detail"].lower()


@patch("app.api.discord.DISCORD_BOT_TOKEN", "test-bot-token")
@patch("app.api.discord.httpx.Client")
def test_callback_channel_creation_network_error_returns_502(
    mock_httpx_client_cls, test_client, auth_header
):
    """Network error when creating channel -> 502."""
    mock_httpx_client_cls.side_effect = None
    mock_httpx_client_cls.return_value = _mock_httpx_for_bot(
        channel_side_effect=httpx.ConnectError("Connection refused"),
    ).return_value

    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 502
    assert "discord" in resp.json()["detail"].lower()


@patch("app.api.discord.DISCORD_BOT_TOKEN", "test-bot-token")
@patch("app.api.discord.httpx.Client")
def test_callback_webhook_creation_fails_returns_502(
    mock_httpx_client_cls, test_client, auth_header
):
    """Channel created but webhook creation fails -> 502."""
    mock_httpx_client_cls.side_effect = None
    mock_httpx_client_cls.return_value = _mock_httpx_for_bot(
        webhook_status=500,
        webhook_json={"message": "Internal Server Error"},
    ).return_value

    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 502
    assert "webhook" in resp.json()["detail"].lower()


@patch("app.api.discord.DISCORD_BOT_TOKEN", "")
def test_callback_bot_token_not_configured_returns_503(test_client, auth_header):
    """Missing bot token -> 503."""
    resp = test_client.post(
        "/api/discord/callback",
        json={"guild_id": "123456789", "permissions": "536870928", "state": "some-state"},
        headers=auth_header,
    )
    assert resp.status_code == 503
    assert "bot token" in resp.json()["detail"].lower()
