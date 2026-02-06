"""Security-focused tests for Reddalert.

Tests cover:
- API key hashing (PBKDF2-SHA256, not plaintext)
- Input validation (subreddit names, webhook URLs, keyword phrases)
- SSRF prevention (Discord-only webhook URLs)
- Rate limiting headers
- Error response safety (no stack trace leakage)
- Client data isolation
- CORS configuration
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import hash_api_key, rate_limiter, verify_api_key
from app.api.schemas import (
    KeywordCreate,
    SubredditCreate,
    WebhookCreate,
)
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.clients import Client
from app.models.keywords import Keyword

# ---------------------------------------------------------------------------
# Test database setup (SQLite in-memory, shared across tests)
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_TestSession = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def _override_get_db() -> Iterator[Session]:
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


_client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _setup_tables():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=_engine)
    app.dependency_overrides[get_db] = _override_get_db
    rate_limiter.reset()
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db_session() -> Iterator[Session]:
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def authenticated_client(db_session: Session):
    """Create a client and return (client_record, raw_key, headers)."""
    raw_key = "test-security-key-abc123"
    hashed = hash_api_key(raw_key)
    c = Client(
        id=uuid.uuid4(),
        api_key=hashed,
        email="security@test.com",
        polling_interval=60,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c, raw_key, {"X-API-Key": raw_key}


# ===================================================================
# 1. API Key Security
# ===================================================================

class TestApiKeySecurity:
    """Verify API key hashing uses PBKDF2-SHA256 and is timing-attack resistant."""

    def test_hash_is_pbkdf2_sha256(self):
        """Hashed key should start with $pbkdf2-sha256$ prefix."""
        hashed = hash_api_key("test-key")
        assert hashed.startswith("$pbkdf2-sha256$"), f"Expected PBKDF2 hash, got: {hashed[:20]}"

    def test_hash_not_plaintext(self):
        raw = "my-secret-api-key"
        hashed = hash_api_key(raw)
        assert raw not in hashed

    def test_verify_correct_key(self):
        raw = "correct-key-123"
        hashed = hash_api_key(raw)
        assert verify_api_key(raw, hashed)

    def test_verify_wrong_key(self):
        hashed = hash_api_key("correct-key")
        assert not verify_api_key("wrong-key", hashed)

    def test_different_keys_different_hashes(self):
        h1 = hash_api_key("key-one")
        h2 = hash_api_key("key-two")
        assert h1 != h2

    def test_same_key_different_hashes(self):
        """PBKDF2 should produce different hashes for the same input (salted)."""
        h1 = hash_api_key("same-key")
        h2 = hash_api_key("same-key")
        assert h1 != h2  # different salts

    def test_api_key_not_in_get_response(self, authenticated_client):
        """GET /clients/me should never return the hashed API key."""
        _, _, headers = authenticated_client
        resp = _client.get("/api/clients/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "api_key" not in data

    def test_create_client_returns_key_once(self):
        """POST /clients returns the plaintext key only on creation."""
        resp = _client.post("/api/clients", json={"email": "new@test.com"})
        assert resp.status_code == 201
        data = resp.json()
        assert "api_key" in data
        assert len(data["api_key"]) > 20


# ===================================================================
# 2. Authentication Error Messages
# ===================================================================

class TestAuthErrorMessages:
    """Verify 401 responses do not leak information about key existence."""

    def test_missing_key_generic_message(self):
        resp = _client.get("/api/clients/me")
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert "Missing" in detail
        assert "client" not in detail.lower()
        assert "database" not in detail.lower()

    def test_invalid_key_generic_message(self, authenticated_client):
        resp = _client.get(
            "/api/clients/me",
            headers={"X-API-Key": "completely-wrong-key-xyz"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert "Invalid" in detail
        assert "not found" not in detail.lower()
        assert "no client" not in detail.lower()


# ===================================================================
# 3. Rate Limiting
# ===================================================================

class TestRateLimiting:
    def test_rate_limit_returns_429(self, authenticated_client):
        _, _, headers = authenticated_client
        rate_limiter.reset()
        original_max = rate_limiter.max_requests
        rate_limiter.max_requests = 2
        try:
            for _ in range(2):
                resp = _client.get("/api/clients/me", headers=headers)
                assert resp.status_code == 200
            resp = _client.get("/api/clients/me", headers=headers)
            assert resp.status_code == 429
        finally:
            rate_limiter.max_requests = original_max

    def test_rate_limit_headers_on_429(self, authenticated_client):
        _, _, headers = authenticated_client
        rate_limiter.reset()
        original_max = rate_limiter.max_requests
        rate_limiter.max_requests = 1
        try:
            _client.get("/api/clients/me", headers=headers)
            resp = _client.get("/api/clients/me", headers=headers)
            assert resp.status_code == 429
            assert "X-RateLimit-Limit" in resp.headers
            assert "X-RateLimit-Remaining" in resp.headers
            assert resp.headers["X-RateLimit-Remaining"] == "0"
            assert "Retry-After" in resp.headers
        finally:
            rate_limiter.max_requests = original_max


# ===================================================================
# 4. Subreddit Name Validation (schema-level)
# ===================================================================

class TestSubredditValidation:
    """Subreddit names must be alphanumeric + underscores, max 50 chars."""

    def test_valid_name(self):
        s = SubredditCreate(name="sportsbook")
        assert s.name == "sportsbook"

    def test_strips_r_prefix(self):
        s = SubredditCreate(name="r/Python")
        assert s.name == "python"

    def test_rejects_special_characters(self):
        for bad_name in ["sports-book", "foo bar", "a/b/c", "test!", "sub@reddit"]:
            with pytest.raises(ValidationError):
                SubredditCreate(name=bad_name)

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            SubredditCreate(name="")

    def test_rejects_too_long_name(self):
        with pytest.raises(ValidationError):
            SubredditCreate(name="a" * 51)

    def test_rejects_script_injection_in_name(self):
        with pytest.raises(ValidationError):
            SubredditCreate(name="<script>alert(1)</script>")


# ===================================================================
# 5. Webhook URL Validation (schema-level, SSRF Prevention)
# ===================================================================

class TestWebhookUrlValidation:
    """Webhook URLs must be valid Discord webhook URLs over HTTPS."""

    def test_valid_discord_url(self):
        w = WebhookCreate(url="https://discord.com/api/webhooks/123456789/abcdef-token")
        assert w.url == "https://discord.com/api/webhooks/123456789/abcdef-token"

    def test_valid_discordapp_url(self):
        w = WebhookCreate(url="https://discordapp.com/api/webhooks/123/abc-def")
        assert "discordapp.com" in w.url

    def test_rejects_http(self):
        with pytest.raises(ValidationError):
            WebhookCreate(url="http://discord.com/api/webhooks/123/abc")

    def test_rejects_non_discord_url(self):
        for bad_url in [
            "https://evil.com/steal-data",
            "https://example.com/webhook",
            "https://attacker.com/api/webhooks/123/abc",
        ]:
            with pytest.raises(ValidationError):
                WebhookCreate(url=bad_url)

    def test_rejects_internal_urls(self):
        for internal_url in [
            "https://localhost/api/webhooks/123/abc",
            "https://127.0.0.1/api/webhooks/123/abc",
            "https://0.0.0.0/api/webhooks/123/abc",
        ]:
            with pytest.raises(ValidationError):
                WebhookCreate(url=internal_url)

    def test_rejects_javascript_url(self):
        with pytest.raises(ValidationError):
            WebhookCreate(url="javascript:alert(1)")


# ===================================================================
# 6. Keyword Phrase Validation (schema-level)
# ===================================================================

class TestKeywordPhraseValidation:
    def test_valid_phrases(self):
        kw = KeywordCreate(phrases=["arbitrage betting", "sports trading"])
        assert len(kw.phrases) == 2

    def test_rejects_empty_phrases(self):
        with pytest.raises(ValidationError):
            KeywordCreate(phrases=[])

    def test_rejects_all_whitespace_phrases(self):
        with pytest.raises(ValidationError):
            KeywordCreate(phrases=["   ", "  "])

    def test_strips_angle_brackets(self):
        kw = KeywordCreate(phrases=["<script>alert(1)</script>"])
        assert "<" not in kw.phrases[0]
        assert ">" not in kw.phrases[0]

    def test_rejects_too_long_phrase(self):
        with pytest.raises(ValidationError):
            KeywordCreate(phrases=["a" * 201])

    def test_rejects_too_many_phrases(self):
        with pytest.raises(ValidationError):
            KeywordCreate(phrases=[f"phrase{i}" for i in range(21)])


# ===================================================================
# 7. Pagination Limits (API-level)
# ===================================================================

class TestPaginationLimits:
    def test_per_page_clamped_to_max(self, authenticated_client):
        _, _, headers = authenticated_client
        resp = _client.get("/api/matches?per_page=999", headers=headers)
        # FastAPI Query validation should reject > 100
        assert resp.status_code == 422

    def test_page_minimum_is_one(self, authenticated_client):
        _, _, headers = authenticated_client
        resp = _client.get("/api/matches?page=0", headers=headers)
        assert resp.status_code == 422


# ===================================================================
# 8. Error Response Safety
# ===================================================================

class TestErrorResponseSafety:
    def test_404_no_internal_paths(self, authenticated_client):
        _, _, headers = authenticated_client
        resp = _client.get("/api/keywords/not-a-uuid", headers=headers)
        body = resp.text
        assert "/Users/" not in body
        assert "Traceback" not in body
        assert "File " not in body

    def test_health_no_sensitive_info(self):
        resp = _client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "database" not in str(data).lower()
        assert "password" not in str(data).lower()


# ===================================================================
# 9. Client Data Isolation
# ===================================================================

class TestClientIsolation:
    def test_cannot_access_other_client_keywords(self, db_session: Session):
        """Client A cannot see or modify Client B's data."""
        key_a = "client-a-isolation-test"
        key_b = "client-b-isolation-test"
        c_a = Client(
            id=uuid.uuid4(),
            api_key=hash_api_key(key_a),
            email="a@test.com",
            polling_interval=60,
        )
        c_b = Client(
            id=uuid.uuid4(),
            api_key=hash_api_key(key_b),
            email="b@test.com",
            polling_interval=60,
        )
        db_session.add_all([c_a, c_b])
        db_session.flush()

        kw = Keyword(
            id=uuid.uuid4(),
            client_id=c_b.id,
            phrases=["secret phrase"],
        )
        db_session.add(kw)
        db_session.commit()

        resp = _client.get(
            "/api/keywords",
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        resp = _client.get(
            f"/api/keywords/{kw.id}",
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 404

        resp = _client.delete(
            f"/api/keywords/{kw.id}",
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 404


# ===================================================================
# 10. CORS Configuration
# ===================================================================

class TestCORSConfiguration:
    def test_cors_allows_frontend_origin(self):
        resp = _client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejects_unknown_origin(self):
        resp = _client.options(
            "/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        allowed = resp.headers.get("access-control-allow-origin", "")
        assert allowed != "http://evil.com"
        assert allowed != "*"


# ===================================================================
# 11. Match Response Safety
# ===================================================================

class TestMatchResponseSafety:
    def test_match_response_no_full_text(self, authenticated_client, db_session: Session):
        """Match API response should not include full_text to minimize data exposure."""
        from app.models.content import ContentType, RedditContent
        from app.models.matches import AlertStatus, Match as MatchModel

        c, _, headers = authenticated_client
        kw = Keyword(
            id=uuid.uuid4(),
            client_id=c.id,
            phrases=["test"],
        )
        db_session.add(kw)
        db_session.flush()

        content = RedditContent(
            id=uuid.uuid4(),
            reddit_id="t3_test",
            subreddit="test",
            content_type=ContentType.post,
            title="Test",
            body="Full text that should not appear in response",
            author="tester",
            normalized_text="full text that should not appear",
            content_hash="testhash123",
            reddit_created_at=datetime.now(timezone.utc),
        )
        db_session.add(content)
        db_session.flush()

        m = MatchModel(
            id=uuid.uuid4(),
            client_id=c.id,
            keyword_id=kw.id,
            content_id=content.id,
            content_type=ContentType.post,
            subreddit="test",
            matched_phrase="test",
            also_matched=[],
            snippet="...test snippet...",
            full_text="Full text that should not appear in response",
            proximity_score=1.0,
            reddit_url="https://reddit.com/r/test/t3_test",
            reddit_author="tester",
            alert_status=AlertStatus.pending,
        )
        db_session.add(m)
        db_session.commit()

        resp = _client.get(f"/api/matches/{m.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "full_text" not in data
