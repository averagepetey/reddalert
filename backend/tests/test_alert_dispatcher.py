"""Tests for the alert dispatcher module."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.matches import AlertStatus, Match
from app.models.webhooks import WebhookConfig
from app.services.alert_dispatcher import (
    BATCH_THRESHOLD,
    BATCH_WINDOW_SECONDS,
    MAX_RETRIES,
    AlertBatch,
    AlertDispatcher,
)


# ---------------------------------------------------------------------------
# Helpers — use MagicMock(spec=...) to avoid SQLAlchemy instrumentation issues
# ---------------------------------------------------------------------------

def _make_match(
    client_id=None,
    subreddit="sportsbook",
    phrase="arbitrage betting",
    also_matched=None,
    alert_status=AlertStatus.pending,
    detected_at=None,
    **overrides,
):
    m = MagicMock(spec=Match)
    defaults = {
        "id": uuid.uuid4(),
        "client_id": client_id or uuid.uuid4(),
        "keyword_id": uuid.uuid4(),
        "content_id": uuid.uuid4(),
        "content_type": "post",
        "subreddit": subreddit,
        "matched_phrase": phrase,
        "also_matched": also_matched or [],
        "snippet": "I love arbitrage betting strategies for finding great opportunities",
        "full_text": "I love arbitrage betting strategies for finding great opportunities in sports.",
        "proximity_score": 1.0,
        "reddit_url": f"https://reddit.com/r/{subreddit}/comments/abc123",
        "reddit_author": "testuser",
        "is_deleted": False,
        "detected_at": detected_at or datetime.now(timezone.utc),
        "alert_sent_at": None,
        "alert_status": alert_status,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_webhook(client_id, url="https://discord.com/api/webhooks/test/token"):
    wh = MagicMock(spec=WebhookConfig)
    wh.id = uuid.uuid4()
    wh.client_id = client_id
    wh.url = url
    wh.is_primary = True
    wh.is_active = True
    wh.last_tested_at = None
    return wh


def _mock_session(pending_matches=None, webhook=None):
    """Build a mock SQLAlchemy session."""
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is Match:
            q.filter.return_value.order_by.return_value.all.return_value = (
                pending_matches or []
            )
        elif model is WebhookConfig:
            q.filter.return_value.first.return_value = webhook
        return q

    session.query.side_effect = query_side_effect
    return session


# ---------------------------------------------------------------------------
# Tests — Single match alert
# ---------------------------------------------------------------------------

class TestSingleMatchAlert:
    """Test sending a single match alert."""

    @patch("app.services.alert_dispatcher.AlertDispatcher._send_webhook", return_value=True)
    def test_single_match_sent_successfully(self, mock_send):
        client_id = uuid.uuid4()
        match = _make_match(client_id=client_id)
        webhook = _make_webhook(client_id)

        session = _mock_session(pending_matches=[match], webhook=webhook)
        dispatcher = AlertDispatcher(session)

        result = dispatcher.dispatch_pending()

        assert result["sent"] == 1
        assert result["failed"] == 0
        assert result["total"] == 1
        assert match.alert_status == AlertStatus.sent
        assert match.alert_sent_at is not None
        mock_send.assert_called_once()

    @patch("app.services.alert_dispatcher.AlertDispatcher._send_webhook", return_value=True)
    def test_no_pending_matches(self, mock_send):
        session = _mock_session(pending_matches=[])
        dispatcher = AlertDispatcher(session)

        result = dispatcher.dispatch_pending()

        assert result == {"sent": 0, "failed": 0, "total": 0}
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — Batching
# ---------------------------------------------------------------------------

class TestBatching:
    """Test batching 3+ matches within the time window."""

    def test_batch_created_for_3_matches_within_window(self):
        client_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        matches = [
            _make_match(client_id=client_id, detected_at=now),
            _make_match(client_id=client_id, detected_at=now + timedelta(seconds=30)),
            _make_match(client_id=client_id, detected_at=now + timedelta(seconds=60)),
        ]
        webhook = _make_webhook(client_id)
        session = _mock_session(pending_matches=matches, webhook=webhook)
        dispatcher = AlertDispatcher(session)

        batches = dispatcher._batch_matches(matches)

        assert len(batches) == 1
        assert batches[0].is_batch is True
        assert len(batches[0].matches) == 3

    def test_no_batch_below_threshold(self):
        client_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        matches = [
            _make_match(client_id=client_id, detected_at=now),
            _make_match(client_id=client_id, detected_at=now + timedelta(seconds=30)),
        ]
        webhook = _make_webhook(client_id)
        session = _mock_session(pending_matches=matches, webhook=webhook)
        dispatcher = AlertDispatcher(session)

        batches = dispatcher._batch_matches(matches)

        # 2 matches => below threshold => 2 individual batches
        assert len(batches) == 2
        assert all(not b.is_batch for b in batches)

    def test_no_batch_outside_window(self):
        client_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        matches = [
            _make_match(client_id=client_id, detected_at=now),
            _make_match(client_id=client_id, detected_at=now + timedelta(seconds=30)),
            _make_match(
                client_id=client_id,
                detected_at=now + timedelta(seconds=BATCH_WINDOW_SECONDS + 10),
            ),
        ]
        webhook = _make_webhook(client_id)
        session = _mock_session(pending_matches=matches, webhook=webhook)
        dispatcher = AlertDispatcher(session)

        batches = dispatcher._batch_matches(matches)

        # Spread beyond window => individual
        assert len(batches) == 3
        assert all(not b.is_batch for b in batches)


# ---------------------------------------------------------------------------
# Tests — Discord embed format
# ---------------------------------------------------------------------------

class TestEmbedFormat:
    """Test Discord embed payload structure."""

    def test_single_embed_structure(self):
        match = _make_match(subreddit="sportsbook", phrase="arbitrage betting")
        payload = AlertDispatcher._format_embed(match)

        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert "Keyword Match" in embed["title"]
        assert "sportsbook" in embed["title"]
        assert embed["url"] == match.reddit_url
        assert embed["color"] == 0xFF4500

        field_names = [f["name"] for f in embed["fields"]]
        assert "Keyword" in field_names
        assert "Subreddit" in field_names
        assert "Author" in field_names

    def test_single_embed_also_matched(self):
        match = _make_match(also_matched=["sports gambling", "betting tools"])
        payload = AlertDispatcher._format_embed(match)
        embed = payload["embeds"][0]

        field_names = [f["name"] for f in embed["fields"]]
        assert "Also Matched" in field_names

        also_field = next(f for f in embed["fields"] if f["name"] == "Also Matched")
        assert "sports gambling" in also_field["value"]
        assert "betting tools" in also_field["value"]

    def test_single_embed_no_also_matched(self):
        match = _make_match(also_matched=[])
        payload = AlertDispatcher._format_embed(match)
        embed = payload["embeds"][0]

        field_names = [f["name"] for f in embed["fields"]]
        assert "Also Matched" not in field_names

    def test_batch_embed_structure(self):
        matches = [
            _make_match(phrase="arbitrage betting"),
            _make_match(phrase="sports gambling"),
            _make_match(phrase="betting tools"),
        ]
        payload = AlertDispatcher._format_batch_embed(matches)

        assert "embeds" in payload
        embed = payload["embeds"][0]
        assert "3 New Keyword Matches" in embed["title"]
        assert len(embed["fields"]) == 3

    def test_snippet_truncated_in_embed(self):
        long_snippet = "x" * 300
        match = _make_match(snippet=long_snippet)
        payload = AlertDispatcher._format_embed(match)

        embed = payload["embeds"][0]
        # description should be at most 200 chars (or 200 + "...")
        assert len(embed["description"]) <= 203


# ---------------------------------------------------------------------------
# Tests — Webhook retry
# ---------------------------------------------------------------------------

class TestWebhookRetry:
    """Test retry logic on webhook failure."""

    @patch("time.sleep")
    @patch("httpx.Client")
    def test_success_on_first_attempt(self, mock_httpx_cls, mock_sleep):
        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value.status_code = 204

        session = MagicMock()
        dispatcher = AlertDispatcher(session)

        result = dispatcher._send_webhook("https://example.com/webhook", {"embeds": []})

        assert result is True
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("httpx.Client")
    def test_retry_on_failure_then_success(self, mock_httpx_cls, mock_sleep):
        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        # Fail first, succeed second
        resp_fail = MagicMock()
        resp_fail.status_code = 500
        resp_ok = MagicMock()
        resp_ok.status_code = 204
        mock_client.post.side_effect = [resp_fail, resp_ok]

        session = MagicMock()
        dispatcher = AlertDispatcher(session)

        result = dispatcher._send_webhook("https://example.com/webhook", {"embeds": []})

        assert result is True
        assert mock_sleep.call_count == 1

    @patch("time.sleep")
    @patch("httpx.Client")
    def test_fails_after_max_retries(self, mock_httpx_cls, mock_sleep):
        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp_fail = MagicMock()
        resp_fail.status_code = 500
        mock_client.post.return_value = resp_fail

        session = MagicMock()
        dispatcher = AlertDispatcher(session)

        result = dispatcher._send_webhook("https://example.com/webhook", {"embeds": []})

        assert result is False
        assert mock_client.post.call_count == MAX_RETRIES
        assert mock_sleep.call_count == MAX_RETRIES - 1


# ---------------------------------------------------------------------------
# Tests — Failure handling
# ---------------------------------------------------------------------------

class TestFailureHandling:
    """Test marking matches as failed after retries exhausted."""

    @patch("app.services.alert_dispatcher.AlertDispatcher._send_webhook", return_value=False)
    def test_match_marked_failed(self, mock_send):
        client_id = uuid.uuid4()
        match = _make_match(client_id=client_id)
        webhook = _make_webhook(client_id)

        session = _mock_session(pending_matches=[match], webhook=webhook)
        dispatcher = AlertDispatcher(session)

        result = dispatcher.dispatch_pending()

        assert result["failed"] == 1
        assert match.alert_status == AlertStatus.failed
        assert match.alert_sent_at is None


# ---------------------------------------------------------------------------
# Tests — alert_sent_at on success
# ---------------------------------------------------------------------------

class TestAlertSentAt:
    """Test that alert_sent_at is set on successful delivery."""

    @patch("app.services.alert_dispatcher.AlertDispatcher._send_webhook", return_value=True)
    def test_alert_sent_at_set(self, mock_send):
        client_id = uuid.uuid4()
        match = _make_match(client_id=client_id)
        webhook = _make_webhook(client_id)

        session = _mock_session(pending_matches=[match], webhook=webhook)
        dispatcher = AlertDispatcher(session)

        before = datetime.now(timezone.utc)
        dispatcher.dispatch_pending()
        after = datetime.now(timezone.utc)

        assert match.alert_sent_at is not None
        assert before <= match.alert_sent_at <= after


# ---------------------------------------------------------------------------
# Tests — AlertBatch dataclass
# ---------------------------------------------------------------------------

class TestAlertBatchDataclass:
    """Test the AlertBatch dataclass."""

    def test_fields(self):
        cid = uuid.uuid4()
        batch = AlertBatch(
            client_id=cid,
            webhook_url="https://example.com",
            matches=[],
            is_batch=False,
        )
        assert batch.client_id == cid
        assert batch.webhook_url == "https://example.com"
        assert batch.matches == []
        assert batch.is_batch is False

    def test_defaults(self):
        cid = uuid.uuid4()
        batch = AlertBatch(client_id=cid, webhook_url="https://example.com")
        assert batch.matches == []
        assert batch.is_batch is False
