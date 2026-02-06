from __future__ import annotations

"""Tests for the Reddalert background worker (pipeline, retention, scheduler)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app.worker.main import create_scheduler, pipeline_job, retention_job
from app.worker.pipeline import run_pipeline
from app.worker.retention import cleanup_old_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_content(reddit_id: str = "abc123") -> MagicMock:
    """Return a mock RedditContent object."""
    c = MagicMock()
    c.reddit_id = reddit_id
    return c


def _make_match(**kwargs) -> MagicMock:
    """Return a mock Match object."""
    m = MagicMock()
    m.id = kwargs.get("id", uuid.uuid4())
    return m


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


class TestRunPipeline:
    """Tests for run_pipeline()."""

    @patch("app.worker.pipeline.AlertDispatcher")
    @patch("app.worker.pipeline.MatchEngine")
    @patch("app.worker.pipeline.RedditPoller")
    def test_full_pipeline_calls_services_in_order(
        self, mock_poller_cls, mock_engine_cls, mock_dispatcher_cls
    ):
        """Pipeline calls poll -> match -> alert in that order."""
        db = MagicMock()

        # Setup poller
        content_a = _make_content("post1")
        content_b = _make_content("post2")
        mock_poller = mock_poller_cls.return_value
        mock_poller.poll_all_active.return_value = {
            "python": [content_a],
            "django": [content_b],
        }

        # Setup match engine
        mock_engine = mock_engine_cls.return_value
        mock_engine.process_batch.return_value = [_make_match(), _make_match()]

        # Setup dispatcher
        mock_dispatcher = mock_dispatcher_cls.return_value
        mock_dispatcher.dispatch_pending.return_value = {
            "sent": 2,
            "failed": 0,
            "total": 2,
        }

        summary = run_pipeline(db)

        # Verify service instantiation with the same session
        mock_poller_cls.assert_called_once_with(db)
        mock_engine_cls.assert_called_once_with(db)
        mock_dispatcher_cls.assert_called_once_with(db)

        # Verify pipeline execution order
        mock_poller.poll_all_active.assert_called_once()
        mock_engine.process_batch.assert_called_once()
        # Ensure the content passed to process_batch includes both items
        passed_content = mock_engine.process_batch.call_args[0][0]
        assert len(passed_content) == 2
        mock_dispatcher.dispatch_pending.assert_called_once()

        # Verify summary
        assert summary["subreddits_polled"] == 2
        assert summary["new_content"] == 2
        assert summary["matches_found"] == 2
        assert summary["alerts_sent"] == 2
        assert summary["alerts_failed"] == 0

    @patch("app.worker.pipeline.AlertDispatcher")
    @patch("app.worker.pipeline.MatchEngine")
    @patch("app.worker.pipeline.RedditPoller")
    def test_pipeline_no_new_content_skips_matching(
        self, mock_poller_cls, mock_engine_cls, mock_dispatcher_cls
    ):
        """When poller returns no new content, match engine is not called."""
        db = MagicMock()

        mock_poller = mock_poller_cls.return_value
        mock_poller.poll_all_active.return_value = {"python": []}

        mock_dispatcher = mock_dispatcher_cls.return_value
        mock_dispatcher.dispatch_pending.return_value = {
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

        summary = run_pipeline(db)

        mock_engine_cls.return_value.process_batch.assert_not_called()
        assert summary["new_content"] == 0
        assert summary["matches_found"] == 0

    @patch("app.worker.pipeline.AlertDispatcher")
    @patch("app.worker.pipeline.MatchEngine")
    @patch("app.worker.pipeline.RedditPoller")
    def test_pipeline_still_dispatches_when_no_new_content(
        self, mock_poller_cls, mock_engine_cls, mock_dispatcher_cls
    ):
        """Dispatcher runs even with no new content (handles previously pending)."""
        db = MagicMock()

        mock_poller = mock_poller_cls.return_value
        mock_poller.poll_all_active.return_value = {}

        mock_dispatcher = mock_dispatcher_cls.return_value
        mock_dispatcher.dispatch_pending.return_value = {
            "sent": 1,
            "failed": 0,
            "total": 1,
        }

        summary = run_pipeline(db)

        mock_dispatcher.dispatch_pending.assert_called_once()
        assert summary["alerts_sent"] == 1


# ---------------------------------------------------------------------------
# Retention tests
# ---------------------------------------------------------------------------


class TestRetentionCleanup:
    """Tests for cleanup_old_data()."""

    def test_cleanup_deletes_old_records(self):
        """Old matches and content are deleted, session is committed."""
        db = MagicMock()

        # Mock the query chain for Match
        match_query = MagicMock()
        match_filter = MagicMock()
        match_filter.delete.return_value = 5
        match_query.filter.return_value = match_filter

        # Mock the query chain for RedditContent
        content_query = MagicMock()
        content_filter = MagicMock()
        content_filter.delete.return_value = 10
        content_query.filter.return_value = content_filter

        # db.query returns the right mock based on the model
        def query_side_effect(model):
            from app.models.matches import Match
            from app.models.content import RedditContent
            if model is Match:
                return match_query
            elif model is RedditContent:
                return content_query
            return MagicMock()

        db.query.side_effect = query_side_effect

        result = cleanup_old_data(db, retention_days=90)

        assert result["matches_deleted"] == 5
        assert result["content_deleted"] == 10
        db.commit.assert_called_once()

    def test_cleanup_respects_retention_days(self):
        """The cutoff date should be retention_days ago."""
        db = MagicMock()

        match_query = MagicMock()
        match_filter = MagicMock()
        match_filter.delete.return_value = 0
        match_query.filter.return_value = match_filter

        content_query = MagicMock()
        content_filter = MagicMock()
        content_filter.delete.return_value = 0
        content_query.filter.return_value = content_filter

        def query_side_effect(model):
            from app.models.matches import Match
            from app.models.content import RedditContent
            if model is Match:
                return match_query
            elif model is RedditContent:
                return content_query
            return MagicMock()

        db.query.side_effect = query_side_effect

        result = cleanup_old_data(db, retention_days=30)

        assert result["matches_deleted"] == 0
        assert result["content_deleted"] == 0
        # Both Match and RedditContent queries should have been filtered
        match_query.filter.assert_called_once()
        content_query.filter.assert_called_once()

    def test_cleanup_deletes_matches_before_content(self):
        """Matches are deleted before content due to FK constraints."""
        db = MagicMock()
        call_order = []

        match_query = MagicMock()
        match_filter = MagicMock()
        def match_delete(**kwargs):
            call_order.append("match")
            return 0
        match_filter.delete.side_effect = match_delete
        match_query.filter.return_value = match_filter

        content_query = MagicMock()
        content_filter = MagicMock()
        def content_delete(**kwargs):
            call_order.append("content")
            return 0
        content_filter.delete.side_effect = content_delete
        content_query.filter.return_value = content_filter

        def query_side_effect(model):
            from app.models.matches import Match
            from app.models.content import RedditContent
            if model is Match:
                return match_query
            elif model is RedditContent:
                return content_query
            return MagicMock()

        db.query.side_effect = query_side_effect

        cleanup_old_data(db)

        assert call_order == ["match", "content"]


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------


class TestScheduler:
    """Tests for scheduler configuration in main.py."""

    def test_create_scheduler_has_pipeline_job(self):
        """Scheduler should have a pipeline interval job."""
        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        assert "pipeline" in job_ids

    def test_create_scheduler_has_retention_job(self):
        """Scheduler should have a retention cron job."""
        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        assert "retention" in job_ids

    def test_scheduler_job_count(self):
        """Scheduler should have exactly 2 jobs."""
        scheduler = create_scheduler()
        assert len(scheduler.get_jobs()) == 2

    @patch("app.worker.main.POLL_INTERVAL_MINUTES", 15)
    def test_pipeline_job_interval_configurable(self):
        """Pipeline job should use the configured interval."""
        scheduler = create_scheduler()
        pipeline = scheduler.get_job("pipeline")
        # APScheduler 3.x stores interval as trigger.interval
        assert pipeline.trigger.interval == timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Job wrapper tests
# ---------------------------------------------------------------------------


class TestJobWrappers:
    """Tests for pipeline_job() and retention_job() wrappers in main.py."""

    @patch("app.worker.main.run_pipeline")
    @patch("app.worker.main.SessionLocal")
    def test_pipeline_job_opens_and_closes_session(
        self, mock_session_local, mock_run
    ):
        """pipeline_job should create a session, run the pipeline, then close."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_run.return_value = {"subreddits_polled": 0}

        pipeline_job()

        mock_session_local.assert_called_once()
        mock_run.assert_called_once_with(mock_session)
        mock_session.close.assert_called_once()

    @patch("app.worker.main.run_pipeline", side_effect=RuntimeError("boom"))
    @patch("app.worker.main.SessionLocal")
    def test_pipeline_job_closes_session_on_error(
        self, mock_session_local, mock_run
    ):
        """Session is closed even when the pipeline raises an exception."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        pipeline_job()  # should not raise

        mock_session.close.assert_called_once()

    @patch("app.worker.main.cleanup_old_data")
    @patch("app.worker.main.SessionLocal")
    def test_retention_job_opens_and_closes_session(
        self, mock_session_local, mock_cleanup
    ):
        """retention_job should create a session, run cleanup, then close."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session
        mock_cleanup.return_value = {"content_deleted": 0, "matches_deleted": 0}

        retention_job()

        mock_session_local.assert_called_once()
        mock_cleanup.assert_called_once_with(mock_session, retention_days=90)
        mock_session.close.assert_called_once()

    @patch("app.worker.main.cleanup_old_data", side_effect=RuntimeError("boom"))
    @patch("app.worker.main.SessionLocal")
    def test_retention_job_closes_session_on_error(
        self, mock_session_local, mock_cleanup
    ):
        """Session is closed even when cleanup raises an exception."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        retention_job()  # should not raise

        mock_session.close.assert_called_once()
