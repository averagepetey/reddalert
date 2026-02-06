"""Tests for REST API endpoints and auth middleware."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Text, create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles as sa_compiles
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import hash_api_key, rate_limiter, verify_api_key
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.clients import Client
from app.models.content import ContentType, RedditContent
from app.models.keywords import Keyword
from app.models.matches import AlertStatus, Match
from app.models.subreddits import MonitoredSubreddit, SubredditStatus
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

VALID_DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1234567890/abcdefghijklmnop"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_db():
    """Create tables, provide shared connection, drop after test."""
    # Use a single connection for all sessions so in-memory SQLite works
    connection = engine.connect()
    transaction = connection.begin()

    # Create tables on this connection
    Base.metadata.create_all(bind=connection)

    # Create a sessionmaker bound to this connection
    TestSession = sessionmaker(bind=connection)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    rate_limiter.reset()

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
def test_client_record(db_session: Session):
    """Create a client with a known API key for authenticated requests."""
    raw_key = "test-api-key-12345"
    hashed = hash_api_key(raw_key)
    c = Client(
        id=uuid.uuid4(),
        api_key=hashed,
        email="test@example.com",
        polling_interval=60,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c, raw_key


@pytest.fixture
def auth_headers(test_client_record):
    """Return headers with valid API key."""
    _, raw_key = test_client_record
    return {"X-API-Key": raw_key}


@pytest.fixture
def test_keyword(db_session: Session, test_client_record):
    """Create a keyword for the test client."""
    c, _ = test_client_record
    kw = Keyword(
        id=uuid.uuid4(),
        client_id=c.id,
        phrases=["arbitrage betting"],
        exclusions=["free"],
        proximity_window=15,
    )
    db_session.add(kw)
    db_session.commit()
    db_session.refresh(kw)
    return kw


@pytest.fixture
def test_subreddit(db_session: Session, test_client_record):
    """Create a monitored subreddit for the test client."""
    c, _ = test_client_record
    sub = MonitoredSubreddit(
        id=uuid.uuid4(),
        client_id=c.id,
        name="sportsbook",
        status=SubredditStatus.active,
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    return sub


@pytest.fixture
def test_webhook(db_session: Session, test_client_record):
    """Create a webhook for the test client."""
    c, _ = test_client_record
    wh = WebhookConfig(
        id=uuid.uuid4(),
        client_id=c.id,
        url=VALID_DISCORD_WEBHOOK,
        is_primary=True,
    )
    db_session.add(wh)
    db_session.commit()
    db_session.refresh(wh)
    return wh


@pytest.fixture
def test_match(db_session: Session, test_client_record, test_keyword):
    """Create a match for the test client."""
    c, _ = test_client_record
    content = RedditContent(
        id=uuid.uuid4(),
        reddit_id="t3_abc123",
        subreddit="sportsbook",
        content_type=ContentType.post,
        title="Test post",
        body="Test body about arbitrage betting",
        author="testuser",
        normalized_text="test body about arbitrage betting",
        content_hash="hash123",
        reddit_created_at=datetime.now(timezone.utc),
    )
    db_session.add(content)
    db_session.flush()

    m = Match(
        id=uuid.uuid4(),
        client_id=c.id,
        keyword_id=test_keyword.id,
        content_id=content.id,
        content_type=ContentType.post,
        subreddit="sportsbook",
        matched_phrase="arbitrage betting",
        also_matched=[],
        snippet="...about arbitrage betting strategies...",
        full_text="Full test body about arbitrage betting",
        proximity_score=0.95,
        reddit_url="https://reddit.com/r/sportsbook/abc123",
        reddit_author="testuser",
        alert_status=AlertStatus.pending,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


# ---------------------------------------------------------------------------
# Auth middleware tests
# ---------------------------------------------------------------------------

class TestAuth:
    def test_missing_api_key(self, test_client):
        resp = test_client.get("/api/clients/me")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    def test_invalid_api_key(self, test_client, test_client_record):
        resp = test_client.get(
            "/api/clients/me",
            headers={"X-API-Key": "totally-wrong-key"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_valid_api_key(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/clients/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@example.com"

    def test_rate_limiting(self, test_client, auth_headers, test_client_record):
        """After max requests, should return 429."""
        rate_limiter.reset()
        original_max = rate_limiter.max_requests
        rate_limiter.max_requests = 3
        try:
            for _ in range(3):
                resp = test_client.get("/api/clients/me", headers=auth_headers)
                assert resp.status_code == 200
            resp = test_client.get("/api/clients/me", headers=auth_headers)
            assert resp.status_code == 429
        finally:
            rate_limiter.max_requests = original_max


class TestApiKeyHashing:
    def test_hash_and_verify(self):
        raw = "my-secret-key-123"
        hashed = hash_api_key(raw)
        assert hashed != raw
        assert verify_api_key(raw, hashed)

    def test_wrong_key_fails(self):
        hashed = hash_api_key("correct-key")
        assert not verify_api_key("wrong-key", hashed)


# ---------------------------------------------------------------------------
# Client endpoint tests
# ---------------------------------------------------------------------------

class TestClientEndpoints:
    def test_create_client(self, test_client):
        resp = test_client.post(
            "/api/clients",
            json={"email": "new@example.com", "polling_interval": 30},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["polling_interval"] == 30
        assert "api_key" in data
        assert len(data["api_key"]) > 20

    def test_create_client_defaults(self, test_client):
        resp = test_client.post("/api/clients", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["polling_interval"] == 60
        assert data["email"] is None

    def test_get_me(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/clients/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert "api_key" not in data

    def test_update_me(self, test_client, auth_headers, test_client_record):
        resp = test_client.patch(
            "/api/clients/me",
            headers=auth_headers,
            json={"email": "updated@example.com", "polling_interval": 15},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "updated@example.com"
        assert data["polling_interval"] == 15

    def test_update_me_partial(self, test_client, auth_headers, test_client_record):
        resp = test_client.patch(
            "/api/clients/me",
            headers=auth_headers,
            json={"email": "partial@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "partial@example.com"
        assert resp.json()["polling_interval"] == 60

    def test_create_client_invalid_interval(self, test_client):
        resp = test_client.post(
            "/api/clients",
            json={"polling_interval": 0},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Keyword endpoint tests
# ---------------------------------------------------------------------------

class TestKeywordEndpoints:
    def test_list_keywords_empty(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/keywords", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_keyword(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/keywords",
            headers=auth_headers,
            json={
                "phrases": ["arbitrage betting", "sports arbitrage"],
                "exclusions": ["free", "trial"],
                "proximity_window": 10,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["phrases"] == ["arbitrage betting", "sports arbitrage"]
        assert data["exclusions"] == ["free", "trial"]
        assert data["proximity_window"] == 10
        assert data["is_active"] is True

    def test_create_keyword_empty_phrases_rejected(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/keywords",
            headers=auth_headers,
            json={"phrases": []},
        )
        assert resp.status_code == 422

    def test_create_keyword_whitespace_phrases_rejected(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/keywords",
            headers=auth_headers,
            json={"phrases": ["   ", ""]},
        )
        assert resp.status_code == 422

    def test_get_keyword(self, test_client, auth_headers, test_keyword):
        resp = test_client.get(
            f"/api/keywords/{test_keyword.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["phrases"] == ["arbitrage betting"]

    def test_get_keyword_not_found(self, test_client, auth_headers, test_client_record):
        fake_id = uuid.uuid4()
        resp = test_client.get(
            f"/api/keywords/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_update_keyword(self, test_client, auth_headers, test_keyword):
        resp = test_client.patch(
            f"/api/keywords/{test_keyword.id}",
            headers=auth_headers,
            json={"proximity_window": 20, "use_stemming": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["proximity_window"] == 20
        assert data["use_stemming"] is True
        assert data["phrases"] == ["arbitrage betting"]

    def test_delete_keyword_soft(self, test_client, auth_headers, test_keyword):
        resp = test_client.delete(
            f"/api/keywords/{test_keyword.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        resp = test_client.get("/api/keywords", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_list_keywords_after_create(self, test_client, auth_headers, test_keyword):
        resp = test_client.get("/api/keywords", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Subreddit endpoint tests
# ---------------------------------------------------------------------------

class TestSubredditEndpoints:
    def test_list_subreddits_empty(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/subreddits", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_subreddit(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/subreddits",
            headers=auth_headers,
            json={"name": "sportsbook"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "sportsbook"
        assert data["status"] == "active"

    def test_add_subreddit_strips_prefix(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/subreddits",
            headers=auth_headers,
            json={"name": "r/Python"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "python"

    def test_add_duplicate_subreddit(self, test_client, auth_headers, test_subreddit):
        resp = test_client.post(
            "/api/subreddits",
            headers=auth_headers,
            json={"name": "sportsbook"},
        )
        assert resp.status_code == 409

    def test_remove_subreddit(self, test_client, auth_headers, test_subreddit):
        resp = test_client.delete(
            f"/api/subreddits/{test_subreddit.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        resp = test_client.get("/api/subreddits", headers=auth_headers)
        assert len(resp.json()) == 0

    def test_remove_nonexistent_subreddit(self, test_client, auth_headers, test_client_record):
        fake_id = uuid.uuid4()
        resp = test_client.delete(
            f"/api/subreddits/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_add_subreddit_empty_name(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/subreddits",
            headers=auth_headers,
            json={"name": ""},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Webhook endpoint tests
# ---------------------------------------------------------------------------

class TestWebhookEndpoints:
    def test_list_webhooks_empty(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/webhooks", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_webhook(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/webhooks",
            headers=auth_headers,
            json={"url": VALID_DISCORD_WEBHOOK},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == VALID_DISCORD_WEBHOOK
        assert data["is_primary"] is True

    def test_create_webhook_http_rejected(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/webhooks",
            headers=auth_headers,
            json={"url": "http://not-secure.com/webhook"},
        )
        assert resp.status_code == 422

    def test_create_webhook_non_discord_rejected(self, test_client, auth_headers, test_client_record):
        resp = test_client.post(
            "/api/webhooks",
            headers=auth_headers,
            json={"url": "https://evil.com/api/webhooks/123/abc"},
        )
        assert resp.status_code == 422

    def test_test_webhook(self, test_client, auth_headers, test_webhook):
        resp = test_client.post(
            f"/api/webhooks/{test_webhook.id}/test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_test_webhook_not_found(self, test_client, auth_headers, test_client_record):
        fake_id = uuid.uuid4()
        resp = test_client.post(
            f"/api/webhooks/{fake_id}/test",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_webhook(self, test_client, auth_headers, test_webhook):
        resp = test_client.delete(
            f"/api/webhooks/{test_webhook.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        resp = test_client.get("/api/webhooks", headers=auth_headers)
        assert len(resp.json()) == 0

    def test_delete_webhook_not_found(self, test_client, auth_headers, test_client_record):
        fake_id = uuid.uuid4()
        resp = test_client.delete(
            f"/api/webhooks/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Match endpoint tests
# ---------------------------------------------------------------------------

class TestMatchEndpoints:
    def test_list_matches_empty(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/matches", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_matches(self, test_client, auth_headers, test_match):
        resp = test_client.get("/api/matches", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["matched_phrase"] == "arbitrage betting"

    def test_list_matches_pagination(self, test_client, auth_headers, test_match):
        resp = test_client.get(
            "/api/matches?page=1&per_page=1",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["per_page"] == 1
        assert data["page"] == 1

    def test_list_matches_filter_subreddit(self, test_client, auth_headers, test_match):
        resp = test_client.get(
            "/api/matches?subreddit=sportsbook",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = test_client.get(
            "/api/matches?subreddit=nonexistent",
            headers=auth_headers,
        )
        assert resp.json()["total"] == 0

    def test_list_matches_filter_keyword(self, test_client, auth_headers, test_match, test_keyword):
        resp = test_client.get(
            f"/api/matches?keyword_id={test_keyword.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_match(self, test_client, auth_headers, test_match):
        resp = test_client.get(
            f"/api/matches/{test_match.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["matched_phrase"] == "arbitrage betting"

    def test_get_match_not_found(self, test_client, auth_headers, test_client_record):
        fake_id = uuid.uuid4()
        resp = test_client.get(
            f"/api/matches/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Stats endpoint tests
# ---------------------------------------------------------------------------

class TestStatsEndpoints:
    def test_stats_empty(self, test_client, auth_headers, test_client_record):
        resp = test_client.get("/api/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_matches"] == 0
        assert data["matches_last_24h"] == 0
        assert data["top_keywords"] == []
        assert data["top_subreddits"] == []

    def test_stats_with_data(self, test_client, auth_headers, test_match, test_keyword):
        resp = test_client.get("/api/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_matches"] == 1
        assert data["matches_last_24h"] == 1
        assert data["matches_last_7d"] == 1
        assert len(data["top_keywords"]) == 1
        assert data["top_keywords"][0]["match_count"] == 1
        assert len(data["top_subreddits"]) == 1
        assert data["top_subreddits"][0]["subreddit"] == "sportsbook"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Cross-client isolation tests
# ---------------------------------------------------------------------------

class TestClientIsolation:
    def test_cannot_see_other_clients_keywords(self, test_client, db_session: Session):
        """Client A should not see Client B's keywords."""
        key_a = "client-a-key-12345"
        client_a = Client(
            id=uuid.uuid4(),
            api_key=hash_api_key(key_a),
            email="a@test.com",
            polling_interval=60,
        )
        db_session.add(client_a)
        db_session.flush()

        key_b = "client-b-key-12345"
        client_b = Client(
            id=uuid.uuid4(),
            api_key=hash_api_key(key_b),
            email="b@test.com",
            polling_interval=60,
        )
        db_session.add(client_b)
        db_session.flush()

        kw = Keyword(
            id=uuid.uuid4(),
            client_id=client_b.id,
            phrases=["secret keyword"],
        )
        db_session.add(kw)
        db_session.commit()

        resp = test_client.get(
            "/api/keywords",
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 200
        assert resp.json() == []

        resp = test_client.get(
            "/api/keywords",
            headers={"X-API-Key": key_b},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
