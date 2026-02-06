"""Tests for the match engine module."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.models.clients import Client
from app.models.content import ContentType, RedditContent
from app.models.keywords import Keyword
from app.models.matches import AlertStatus, Match
from app.models.subreddits import MonitoredSubreddit, SubredditStatus
from app.services.match_engine import MatchEngine
from app.services.matcher import KeywordConfig


# ---------------------------------------------------------------------------
# Helpers — use MagicMock(spec=...) to avoid SQLAlchemy instrumentation issues
# ---------------------------------------------------------------------------

def _make_client(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "api_key": "test-key",
        "email": "test@example.com",
        "polling_interval": 60,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    c = MagicMock(spec=Client)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _make_keyword(client, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "client_id": client.id,
        "phrases": ["arbitrage betting"],
        "exclusions": [],
        "proximity_window": 15,
        "require_order": False,
        "use_stemming": False,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "client": client,
        "matches": [],
    }
    defaults.update(overrides)
    kw = MagicMock(spec=Keyword)
    for k, v in defaults.items():
        setattr(kw, k, v)
    return kw


def _make_content(text, subreddit="sportsbook", **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "reddit_id": f"t3_{uuid.uuid4().hex[:8]}",
        "subreddit": subreddit,
        "content_type": ContentType.post,
        "title": "Test post",
        "body": text,
        "author": "testuser",
        "normalized_text": text.lower(),
        "content_hash": uuid.uuid4().hex,
        "reddit_created_at": datetime.now(timezone.utc),
        "fetched_at": datetime.now(timezone.utc),
        "is_deleted": False,
        "matches": [],
    }
    defaults.update(overrides)
    rc = MagicMock(spec=RedditContent)
    for k, v in defaults.items():
        setattr(rc, k, v)
    return rc


def _make_monitored_sub(client, name="sportsbook"):
    sub = MagicMock(spec=MonitoredSubreddit)
    sub.id = uuid.uuid4()
    sub.client_id = client.id
    sub.name = name
    sub.status = SubredditStatus.active
    sub.include_media_posts = True
    sub.dedupe_crossposts = True
    sub.filter_bots = False
    sub.last_polled_at = None
    sub.client = client
    return sub


def _mock_session(monitored_subs=None, keywords=None):
    """Build a mock SQLAlchemy session with chained query support."""
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is MonitoredSubreddit:
            q.filter.return_value.all.return_value = monitored_subs or []
        elif model is Keyword:
            q.filter.return_value.all.return_value = keywords or []
        else:
            q.filter.return_value.all.return_value = []
        return q

    session.query.side_effect = query_side_effect
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProcessContent:
    """Test processing content that matches a keyword."""

    def test_matching_content_creates_match(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        sub = _make_monitored_sub(client)
        content = _make_content("I love arbitrage betting strategies")

        session = _mock_session(monitored_subs=[sub], keywords=[keyword])
        engine = MatchEngine(session)

        matches = engine.process_content(content)

        assert len(matches) == 1
        m = matches[0]
        assert m.client_id == client.id
        assert m.keyword_id == keyword.id
        assert m.content_id == content.id
        assert m.matched_phrase == "arbitrage betting"
        assert m.alert_status == AlertStatus.pending
        session.add.assert_called()
        session.commit.assert_called_once()

    def test_no_match_returns_empty(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        sub = _make_monitored_sub(client)
        content = _make_content("I enjoy cooking and reading")

        session = _mock_session(monitored_subs=[sub], keywords=[keyword])
        engine = MatchEngine(session)

        matches = engine.process_content(content)

        assert matches == []
        session.commit.assert_not_called()


class TestMultiClientFanOut:
    """Same content matching keywords from multiple clients."""

    def test_two_clients_both_match(self):
        client_a = _make_client()
        client_b = _make_client()

        kw_a = _make_keyword(client_a, phrases=["arbitrage betting"])
        kw_b = _make_keyword(client_b, phrases=["arbitrage betting"])

        sub_a = _make_monitored_sub(client_a)
        sub_b = _make_monitored_sub(client_b)

        content = _make_content("I love arbitrage betting strategies")

        # We need separate keyword queries per client.
        call_count = {"kw": 0}

        def query_side_effect(model):
            q = MagicMock()
            if model is MonitoredSubreddit:
                q.filter.return_value.all.return_value = [sub_a, sub_b]
            elif model is Keyword:
                if call_count["kw"] == 0:
                    q.filter.return_value.all.return_value = [kw_a]
                else:
                    q.filter.return_value.all.return_value = [kw_b]
                call_count["kw"] += 1
            return q

        session = MagicMock()
        session.query.side_effect = query_side_effect

        engine = MatchEngine(session)
        matches = engine.process_content(content)

        assert len(matches) == 2
        client_ids = {m.client_id for m in matches}
        assert client_a.id in client_ids
        assert client_b.id in client_ids


class TestMultiKeywordMatches:
    """Test also_matched population when multiple keywords match."""

    def test_also_matched_populated(self):
        client = _make_client()
        kw1 = _make_keyword(client, phrases=["arbitrage betting"])
        kw2 = _make_keyword(client, phrases=["betting strategies"])

        sub = _make_monitored_sub(client)
        content = _make_content("I love arbitrage betting strategies for sports")

        session = _mock_session(
            monitored_subs=[sub],
            keywords=[kw1, kw2],
        )
        engine = MatchEngine(session)
        matches = engine.process_content(content)

        # Both keywords should match
        assert len(matches) >= 2

        # Each match should have the other phrase in also_matched
        for m in matches:
            if m.matched_phrase == "arbitrage betting":
                assert "betting strategies" in m.also_matched
            elif m.matched_phrase == "betting strategies":
                assert "arbitrage betting" in m.also_matched


class TestKeywordToConfig:
    """Test conversion of Keyword model to KeywordConfig dataclass."""

    def test_basic_conversion(self):
        client = _make_client()
        keyword = _make_keyword(
            client,
            phrases=["arbitrage betting", "sports gambling"],
            exclusions=["scam", "fraud"],
            proximity_window=10,
            require_order=True,
            use_stemming=True,
        )

        config = MatchEngine._keyword_to_config(keyword)

        assert isinstance(config, KeywordConfig)
        assert config.phrases == [["arbitrage", "betting"], ["sports", "gambling"]]
        assert config.exclusions == ["scam", "fraud"]
        assert config.proximity_window == 10
        assert config.require_order is True
        assert config.use_stemming is True

    def test_single_word_phrases(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage"])

        config = MatchEngine._keyword_to_config(keyword)
        assert config.phrases == [["arbitrage"]]

    def test_empty_phrases(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=[])

        config = MatchEngine._keyword_to_config(keyword)
        assert config.phrases == []


class TestProcessBatch:
    """Test processing multiple content items."""

    def test_batch_processes_all(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        sub = _make_monitored_sub(client)

        content1 = _make_content("I love arbitrage betting strategies")
        content2 = _make_content("Another post about arbitrage betting")
        content3 = _make_content("No keywords here")

        session = _mock_session(monitored_subs=[sub], keywords=[keyword])
        engine = MatchEngine(session)

        matches = engine.process_batch([content1, content2, content3])

        # content1 and content2 should match, content3 should not
        assert len(matches) == 2
