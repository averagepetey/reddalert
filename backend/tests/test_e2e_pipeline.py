"""End-to-end integration tests for the Reddalert pipeline.

Tests the full poll -> match -> alert cycle using mocked external I/O
(Reddit API, Discord webhooks) but real internal service logic
(normalizer, matcher, match_engine, alert_dispatcher, deduplicator).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.clients import Client
from app.models.content import ContentType, RedditContent
from app.models.keywords import Keyword
from app.models.matches import AlertStatus, Match
from app.models.subreddits import MonitoredSubreddit, SubredditStatus
from app.models.webhooks import WebhookConfig
from app.services.match_engine import MatchEngine
from app.services.alert_dispatcher import AlertDispatcher
from app.services.normalizer import normalize_text
from app.services.deduplicator import compute_content_hash
from app.worker.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers -- MagicMock-based model factories (avoids SQLite ARRAY issues)
# ---------------------------------------------------------------------------

def _make_client(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "email": "client@example.com",
        "password_hash": "hashed",
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
    normalized = normalize_text(text)
    defaults = {
        "id": uuid.uuid4(),
        "reddit_id": f"t3_{uuid.uuid4().hex[:8]}",
        "subreddit": subreddit,
        "content_type": ContentType.post,
        "title": "Test post",
        "body": text,
        "author": "testuser",
        "normalized_text": normalized.normalized_text,
        "content_hash": compute_content_hash(normalized.normalized_text),
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
    sub.client = client
    return sub


def _make_webhook(client, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "client_id": client.id,
        "url": "https://discord.com/api/webhooks/123/abc",
        "is_primary": True,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "client": client,
    }
    defaults.update(overrides)
    wh = MagicMock(spec=WebhookConfig)
    for k, v in defaults.items():
        setattr(wh, k, v)
    return wh


def _make_match(client, keyword, content, **overrides):
    """Create a mock Match with realistic defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "client_id": client.id,
        "keyword_id": keyword.id,
        "content_id": content.id,
        "content_type": content.content_type,
        "subreddit": content.subreddit,
        "matched_phrase": "arbitrage betting",
        "also_matched": [],
        "snippet": content.body[:200] if content.body else "",
        "full_text": content.body or "",
        "proximity_score": 1.0,
        "reddit_url": f"https://reddit.com/r/{content.subreddit}/comments/{content.reddit_id}",
        "reddit_author": content.author,
        "is_deleted": False,
        "detected_at": datetime.now(timezone.utc),
        "alert_sent_at": None,
        "alert_status": AlertStatus.pending,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    m = MagicMock(spec=Match)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_session_for_match_engine(monitored_subs=None, keywords=None):
    """Build a mock SQLAlchemy session for MatchEngine queries."""
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is MonitoredSubreddit:
            q.filter.return_value.all.return_value = monitored_subs or []
        elif model is Keyword:
            q.filter.return_value.all.return_value = keywords or []
        else:
            # Match.id duplicate check -> no existing match
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    session.query.side_effect = query_side_effect
    return session


def _mock_session_for_dispatcher(pending_matches, webhook=None):
    """Build a mock SQLAlchemy session for AlertDispatcher queries."""
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is Match:
            q.filter.return_value.order_by.return_value.all.return_value = pending_matches
        elif model is WebhookConfig:
            # First call: primary webhook query. Second call: fallback.
            q.filter.return_value.first.return_value = webhook
        elif model is Client:
            # _handle_failure queries for client email
            client_mock = MagicMock(spec=Client)
            client_mock.email = "client@example.com"
            q.filter.return_value.first.return_value = client_mock
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    session.query.side_effect = query_side_effect
    return session


# ---------------------------------------------------------------------------
# Test 1: Matching content produces alert
# ---------------------------------------------------------------------------

class TestMatchingContentProducesAlert:
    """Full flow: content matches keyword -> match created -> alert dispatched."""

    def test_matching_content_produces_alert(self):
        # Setup: client with keyword and webhook
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        sub = _make_monitored_sub(client)
        webhook = _make_webhook(client)
        content = _make_content(
            "I love arbitrage betting strategies for sports",
            subreddit="sportsbook",
        )

        # Step 1: Run MatchEngine with real matching logic
        me_session = _mock_session_for_match_engine(
            monitored_subs=[sub],
            keywords=[keyword],
        )
        engine = MatchEngine(me_session)
        matches = engine.process_content(content)

        assert len(matches) >= 1
        match = matches[0]
        assert match.matched_phrase == "arbitrage betting"
        assert match.alert_status == AlertStatus.pending
        me_session.commit.assert_called_once()

        # Step 2: Dispatch the match via AlertDispatcher with mocked httpx
        disp_session = _mock_session_for_dispatcher(
            pending_matches=[match],
            webhook=webhook,
        )

        with patch("app.services.alert_dispatcher.httpx.Client") as mock_httpx_cls:
            mock_http_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_http_client.post.return_value = mock_response
            mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
            mock_http_client.__exit__ = MagicMock(return_value=False)
            mock_httpx_cls.return_value = mock_http_client

            dispatcher = AlertDispatcher(disp_session)
            result = dispatcher.dispatch_pending()

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert result["total"] == 1
        assert match.alert_status == AlertStatus.sent
        assert match.alert_sent_at is not None


# ---------------------------------------------------------------------------
# Test 2: Non-matching content produces no matches
# ---------------------------------------------------------------------------

class TestNonMatchingContentNoMatches:
    """Content that does not match any keyword produces no matches."""

    def test_non_matching_content_no_matches(self):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        sub = _make_monitored_sub(client)
        content = _make_content(
            "I really enjoy cooking pasta and baking bread",
            subreddit="sportsbook",
        )

        session = _mock_session_for_match_engine(
            monitored_subs=[sub],
            keywords=[keyword],
        )
        engine = MatchEngine(session)
        matches = engine.process_content(content)

        assert matches == []
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: Duplicate content not reprocessed
# ---------------------------------------------------------------------------

class TestDuplicateContentNotReprocessed:
    """Content with the same hash as existing content is skipped by deduplicator."""

    def test_duplicate_content_not_reprocessed(self):
        # The deduplicator's is_duplicate queries the DB for an existing hash.
        text = "this is a test post about arbitrage betting"
        normalized = normalize_text(text)
        content_hash = compute_content_hash(normalized.normalized_text)

        session = MagicMock()

        # Simulate: first call to is_duplicate returns existing record (truthy)
        existing_record = MagicMock()
        existing_record.id = uuid.uuid4()

        def query_side_effect(model_attr):
            q = MagicMock()
            # is_duplicate queries RedditContent.id filtered by content_hash
            q.filter.return_value.first.return_value = existing_record
            return q

        session.query.side_effect = query_side_effect

        from app.services.deduplicator import is_duplicate
        assert is_duplicate(session, content_hash) is True

        # When is_duplicate returns True, the poller skips storing the content.
        # Verify that a second piece of content with the same text produces
        # the same hash, confirming the dedup logic is deterministic.
        text2 = "this is a test post about arbitrage betting"
        normalized2 = normalize_text(text2)
        content_hash2 = compute_content_hash(normalized2.normalized_text)
        assert content_hash == content_hash2


# ---------------------------------------------------------------------------
# Test 4: Webhook failure marks alert as failed
# ---------------------------------------------------------------------------

class TestWebhookFailureMarksAlertFailed:
    """When the Discord webhook returns an error, alert_status becomes 'failed'."""

    @patch("time.sleep")
    def test_webhook_failure_marks_alert_failed(self, mock_sleep):
        client = _make_client()
        keyword = _make_keyword(client, phrases=["arbitrage betting"])
        content = _make_content("arbitrage betting strategies")
        webhook = _make_webhook(client)
        match = _make_match(client, keyword, content)

        session = _mock_session_for_dispatcher(
            pending_matches=[match],
            webhook=webhook,
        )

        with patch("app.services.alert_dispatcher.httpx.Client") as mock_httpx_cls:
            mock_http_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_http_client.post.return_value = mock_response
            mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
            mock_http_client.__exit__ = MagicMock(return_value=False)
            mock_httpx_cls.return_value = mock_http_client

            dispatcher = AlertDispatcher(session)
            result = dispatcher.dispatch_pending()

        assert result["sent"] == 0
        assert result["failed"] == 1
        assert result["total"] == 1
        assert match.alert_status == AlertStatus.failed


# ---------------------------------------------------------------------------
# Test 5: run_pipeline orchestrator
# ---------------------------------------------------------------------------

class TestRunPipelineOrchestrator:
    """Test that run_pipeline chains poller -> match_engine -> alert_dispatcher."""

    @patch("app.worker.pipeline.AlertDispatcher")
    @patch("app.worker.pipeline.MatchEngine")
    @patch("app.worker.pipeline.RedditPoller")
    def test_run_pipeline_orchestrator(
        self, MockPoller, MockMatchEngine, MockAlertDispatcher
    ):
        session = MagicMock()

        # Setup mock poller: returns 2 subreddits with content
        content1 = _make_content("arbitrage betting post")
        content2 = _make_content("another post here")
        mock_poller_instance = MagicMock()
        mock_poller_instance.poll_all_active.return_value = {
            "sportsbook": [content1],
            "gambling": [content2],
        }
        MockPoller.return_value = mock_poller_instance

        # Setup mock match engine: returns 1 match
        mock_match = MagicMock(spec=Match)
        mock_engine_instance = MagicMock()
        mock_engine_instance.process_batch.return_value = [mock_match]
        MockMatchEngine.return_value = mock_engine_instance

        # Setup mock alert dispatcher: returns summary
        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.dispatch_pending.return_value = {
            "sent": 1,
            "failed": 0,
            "total": 1,
        }
        MockAlertDispatcher.return_value = mock_dispatcher_instance

        # Run the pipeline
        summary = run_pipeline(session)

        # Verify execution order and results
        MockPoller.assert_called_once_with(session)
        mock_poller_instance.poll_all_active.assert_called_once()

        MockMatchEngine.assert_called_once_with(session)
        mock_engine_instance.process_batch.assert_called_once()
        # Verify the batch contained both content items
        batch_arg = mock_engine_instance.process_batch.call_args[0][0]
        assert len(batch_arg) == 2

        MockAlertDispatcher.assert_called_once_with(session)
        mock_dispatcher_instance.dispatch_pending.assert_called_once()

        # Verify summary
        assert summary["subreddits_polled"] == 2
        assert summary["new_content"] == 2
        assert summary["matches_found"] == 1
        assert summary["alerts_sent"] == 1
        assert summary["alerts_failed"] == 0

    @patch("app.worker.pipeline.AlertDispatcher")
    @patch("app.worker.pipeline.MatchEngine")
    @patch("app.worker.pipeline.RedditPoller")
    def test_run_pipeline_no_content_skips_matching(
        self, MockPoller, MockMatchEngine, MockAlertDispatcher
    ):
        """When poller returns no content, match engine is not invoked."""
        session = MagicMock()

        mock_poller_instance = MagicMock()
        mock_poller_instance.poll_all_active.return_value = {}
        MockPoller.return_value = mock_poller_instance

        mock_dispatcher_instance = MagicMock()
        mock_dispatcher_instance.dispatch_pending.return_value = {
            "sent": 0,
            "failed": 0,
            "total": 0,
        }
        MockAlertDispatcher.return_value = mock_dispatcher_instance

        summary = run_pipeline(session)

        # Match engine should NOT be instantiated when there's no content
        MockMatchEngine.assert_not_called()

        assert summary["subreddits_polled"] == 0
        assert summary["new_content"] == 0
        assert summary["matches_found"] == 0
