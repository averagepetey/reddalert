from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.bot.utils import get_client_for_guild, parse_duration
from app.models.base import Base
from app.models.clients import Client
from app.models.keywords import Keyword, SilencedPhrase
from app.models.subreddits import MonitoredSubreddit
from app.models.webhooks import WebhookConfig


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db: Session) -> Client:
    c = Client(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="fakehash",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def webhook(db: Session, client: Client) -> WebhookConfig:
    wh = WebhookConfig(
        client_id=client.id,
        url="https://discord.com/api/webhooks/123/abc",
        guild_id="999",
        channel_id="888",
        is_primary=True,
    )
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@pytest.fixture()
def active_keyword(db: Session, client: Client) -> Keyword:
    kw = Keyword(
        client_id=client.id,
        phrases=["arb", "arbitrage"],
        exclusions=[],
        is_active=True,
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return kw


# ---------------------------------------------------------------------------
# parse_duration tests
# ---------------------------------------------------------------------------

class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("20m") == timedelta(minutes=20)

    def test_hours(self):
        assert parse_duration("2h") == timedelta(hours=2)

    def test_days(self):
        assert parse_duration("1d") == timedelta(days=1)

    def test_seconds(self):
        assert parse_duration("30s") == timedelta(seconds=30)

    def test_with_spaces(self):
        assert parse_duration("  20m  ") == timedelta(minutes=20)

    def test_uppercase(self):
        assert parse_duration("20M") == timedelta(minutes=20)

    def test_invalid_format(self):
        assert parse_duration("abc") is None

    def test_empty(self):
        assert parse_duration("") is None

    def test_zero(self):
        assert parse_duration("0m") is None

    def test_exceeds_max(self):
        assert parse_duration("31d") is None

    def test_at_max(self):
        assert parse_duration("30d") == timedelta(days=30)

    def test_negative_not_matched(self):
        assert parse_duration("-5m") is None


# ---------------------------------------------------------------------------
# get_client_for_guild tests
# ---------------------------------------------------------------------------

class TestGetClientForGuild:
    def test_found(self, db, client, webhook):
        result = get_client_for_guild(db, "999")
        assert result is not None
        assert result.id == client.id

    def test_not_found(self, db, client, webhook):
        result = get_client_for_guild(db, "000")
        assert result is None

    def test_inactive_webhook_ignored(self, db, client):
        wh = WebhookConfig(
            client_id=client.id,
            url="https://discord.com/api/webhooks/456/def",
            guild_id="777",
            channel_id="666",
            is_primary=True,
            is_active=False,
        )
        db.add(wh)
        db.commit()
        result = get_client_for_guild(db, "777")
        assert result is None


# ---------------------------------------------------------------------------
# /remove command logic tests
# ---------------------------------------------------------------------------

class TestRemoveSingleKeyword:
    def test_deactivates_keyword(self, db, client, webhook, active_keyword):
        # Simulate: find keyword by phrase, deactivate it
        kw = (
            db.query(Keyword)
            .filter(Keyword.client_id == client.id, Keyword.is_active.is_(True))
            .all()
        )
        matches = [
            k for k in kw
            if any("arb" == p.lower() for p in (k.phrases or []))
        ]
        assert len(matches) == 1
        matched = matches[0]
        matched.is_active = False
        db.commit()
        db.refresh(matched)
        assert matched.is_active is False

    def test_with_duration_sets_silenced_until(self, db, client, webhook, active_keyword):
        td = parse_duration("20m")
        assert td is not None

        reactivate_at = datetime.now(timezone.utc) + td
        active_keyword.is_active = False
        active_keyword.silenced_until = reactivate_at
        db.commit()
        db.refresh(active_keyword)

        assert active_keyword.is_active is False
        assert active_keyword.silenced_until is not None
        # SQLite strips tzinfo; compare as naive UTC
        silenced = active_keyword.silenced_until.replace(tzinfo=None)
        assert silenced > datetime.utcnow()


class TestRemoveMultipleMatches:
    def test_multiple_keywords_match_same_phrase(self, db, client, webhook):
        kw1 = Keyword(
            client_id=client.id,
            phrases=["arb", "arbitrage"],
            exclusions=[],
            is_active=True,
        )
        kw2 = Keyword(
            client_id=client.id,
            phrases=["arb", "arbiter"],
            exclusions=[],
            is_active=True,
        )
        db.add_all([kw1, kw2])
        db.commit()

        all_kw = (
            db.query(Keyword)
            .filter(Keyword.client_id == client.id, Keyword.is_active.is_(True))
            .all()
        )
        matches = [
            k for k in all_kw
            if any("arb" == p.lower() for p in (k.phrases or []))
        ]
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# Channel restriction tests
# ---------------------------------------------------------------------------

class TestChannelRestriction:
    def test_correct_channel(self, db, client, webhook):
        # Channel matches
        wh = (
            db.query(WebhookConfig)
            .filter(WebhookConfig.guild_id == "999", WebhookConfig.is_active.is_(True))
            .first()
        )
        assert wh is not None
        assert wh.channel_id == "888"
        # Simulated interaction channel_id == "888" would pass
        assert str(888) == wh.channel_id

    def test_wrong_channel(self, db, client, webhook):
        wh = (
            db.query(WebhookConfig)
            .filter(WebhookConfig.guild_id == "999", WebhookConfig.is_active.is_(True))
            .first()
        )
        assert wh is not None
        assert str(777) != wh.channel_id


# ---------------------------------------------------------------------------
# /add keyword tests
# ---------------------------------------------------------------------------

class TestAddKeyword:
    def test_creates_keyword(self, db, client, webhook):
        phrase_list = ["test phrase", "another"]
        kw = Keyword(
            client_id=client.id,
            phrases=phrase_list,
            exclusions=[],
        )
        db.add(kw)
        db.commit()

        result = (
            db.query(Keyword)
            .filter(Keyword.client_id == client.id)
            .all()
        )
        assert len(result) == 1
        assert result[0].phrases == ["test phrase", "another"]
        assert result[0].is_active is True

    def test_duplicate_detection(self, db, client, webhook):
        kw1 = Keyword(
            client_id=client.id,
            phrases=["test", "example"],
            exclusions=[],
            is_active=True,
        )
        db.add(kw1)
        db.commit()

        # Check for duplicate
        existing = (
            db.query(Keyword)
            .filter(Keyword.client_id == client.id, Keyword.is_active.is_(True))
            .all()
        )
        new_phrases = ["example", "test"]
        is_dup = any(
            set(p.lower() for p in (kw.phrases or [])) == set(p.lower() for p in new_phrases)
            for kw in existing
        )
        assert is_dup is True


# ---------------------------------------------------------------------------
# /add subreddit tests
# ---------------------------------------------------------------------------

class TestAddSubreddit:
    def test_creates_subreddit(self, db, client, webhook):
        sub = MonitoredSubreddit(
            client_id=client.id,
            name="wallstreetbets",
        )
        db.add(sub)
        db.commit()

        result = (
            db.query(MonitoredSubreddit)
            .filter(MonitoredSubreddit.client_id == client.id)
            .all()
        )
        assert len(result) == 1
        assert result[0].name == "wallstreetbets"

    def test_duplicate_detection(self, db, client, webhook):
        sub = MonitoredSubreddit(
            client_id=client.id,
            name="wallstreetbets",
        )
        db.add(sub)
        db.commit()

        existing = (
            db.query(MonitoredSubreddit)
            .filter(
                MonitoredSubreddit.client_id == client.id,
                MonitoredSubreddit.name == "wallstreetbets",
            )
            .first()
        )
        assert existing is not None

    def test_strips_r_prefix(self):
        name = "r/wallstreetbets"
        cleaned = name.strip().lower()
        if cleaned.startswith("r/"):
            cleaned = cleaned[2:]
        assert cleaned == "wallstreetbets"


# ---------------------------------------------------------------------------
# Reactivation tests
# ---------------------------------------------------------------------------

class TestReactivation:
    def test_reactivate_keyword(self, db, client, active_keyword):
        active_keyword.is_active = False
        active_keyword.silenced_until = datetime.now(timezone.utc) + timedelta(minutes=20)
        db.commit()

        # Simulate reactivation logic
        kw = db.query(Keyword).filter(Keyword.id == active_keyword.id).first()
        assert kw is not None
        kw.is_active = True
        kw.silenced_until = None
        db.commit()
        db.refresh(kw)

        assert kw.is_active is True
        assert kw.silenced_until is None

    def test_expired_keyword_reactivated_on_startup(self, db, client, active_keyword):
        # Set silenced_until to the past
        active_keyword.is_active = False
        active_keyword.silenced_until = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

        # Simulate startup logic: find expired silences and reactivate
        silenced = (
            db.query(Keyword)
            .filter(
                Keyword.silenced_until.isnot(None),
                Keyword.is_active.is_(False),
            )
            .all()
        )
        now = datetime.utcnow()
        for kw in silenced:
            # SQLite strips tzinfo; compare as naive UTC
            silenced_at = kw.silenced_until.replace(tzinfo=None) if kw.silenced_until.tzinfo else kw.silenced_until
            if silenced_at <= now:
                kw.is_active = True
                kw.silenced_until = None
        db.commit()

        db.refresh(active_keyword)
        assert active_keyword.is_active is True
        assert active_keyword.silenced_until is None


# ---------------------------------------------------------------------------
# SilencedPhrase persistence tests
# ---------------------------------------------------------------------------

class TestSilencedPhrasePersistence:
    def test_silenced_phrase_created_on_temp_remove(self, db, client, active_keyword):
        """Removing a phrase with duration creates a SilencedPhrase record."""
        restore_at = datetime.now(timezone.utc) + timedelta(minutes=20)
        # Simulate what /remove does for a multi-phrase keyword with duration
        remaining = [p for p in active_keyword.phrases if p.lower() != "arb"]
        active_keyword.phrases = remaining
        sp = SilencedPhrase(
            keyword_id=active_keyword.id,
            phrase="arb",
            restore_at=restore_at,
        )
        db.add(sp)
        db.commit()

        records = db.query(SilencedPhrase).filter(
            SilencedPhrase.keyword_id == active_keyword.id
        ).all()
        assert len(records) == 1
        assert records[0].phrase == "arb"
        assert "arb" not in active_keyword.phrases
        assert "arbitrage" in active_keyword.phrases

    def test_restore_phrase_adds_back_and_deletes_record(self, db, client, active_keyword):
        """Restoring a phrase adds it back to the array and removes the record."""
        # Remove phrase and create record
        active_keyword.phrases = ["arbitrage"]
        sp = SilencedPhrase(
            keyword_id=active_keyword.id,
            phrase="arb",
            restore_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(sp)
        db.commit()

        # Simulate _restore_phrase logic
        kw = db.query(Keyword).filter(Keyword.id == active_keyword.id).first()
        current = list(kw.phrases or [])
        if "arb" not in [p.lower() for p in current]:
            current.append("arb")
            kw.phrases = current
        db.query(SilencedPhrase).filter(
            SilencedPhrase.keyword_id == active_keyword.id,
            SilencedPhrase.phrase == "arb",
        ).delete()
        db.commit()

        db.refresh(active_keyword)
        assert "arb" in active_keyword.phrases
        assert "arbitrage" in active_keyword.phrases
        remaining = db.query(SilencedPhrase).filter(
            SilencedPhrase.keyword_id == active_keyword.id
        ).all()
        assert len(remaining) == 0

    def test_expired_phrase_restored_on_startup(self, db, client, active_keyword):
        """On startup, expired SilencedPhrase records are restored immediately."""
        active_keyword.phrases = ["arbitrage"]
        sp = SilencedPhrase(
            keyword_id=active_keyword.id,
            phrase="arb",
            restore_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db.add(sp)
        db.commit()

        # Simulate startup logic
        pending = db.query(SilencedPhrase).all()
        now = datetime.utcnow()
        for record in pending:
            restore_at = record.restore_at
            if restore_at.tzinfo:
                restore_at = restore_at.replace(tzinfo=None)
            if restore_at <= now:
                kw = db.query(Keyword).filter(Keyword.id == record.keyword_id).first()
                if kw:
                    current = list(kw.phrases or [])
                    if record.phrase.lower() not in [p.lower() for p in current]:
                        current.append(record.phrase)
                        kw.phrases = current
                db.delete(record)
        db.commit()

        db.refresh(active_keyword)
        assert "arb" in active_keyword.phrases
        assert "arbitrage" in active_keyword.phrases
        remaining = db.query(SilencedPhrase).all()
        assert len(remaining) == 0

    def test_future_phrase_not_restored_on_startup(self, db, client, active_keyword):
        """On startup, future SilencedPhrase records are left for rescheduling."""
        active_keyword.phrases = ["arbitrage"]
        sp = SilencedPhrase(
            keyword_id=active_keyword.id,
            phrase="arb",
            restore_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(sp)
        db.commit()

        # Simulate startup logic — only restore expired ones
        pending = db.query(SilencedPhrase).all()
        now = datetime.utcnow()
        for record in pending:
            restore_at = record.restore_at
            if restore_at.tzinfo:
                restore_at = restore_at.replace(tzinfo=None)
            if restore_at <= now:
                db.delete(record)
        db.commit()

        db.refresh(active_keyword)
        assert "arb" not in active_keyword.phrases
        remaining = db.query(SilencedPhrase).all()
        assert len(remaining) == 1
