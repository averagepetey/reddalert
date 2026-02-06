"""Tests for the Reddit poller service."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.models.content import ContentType, RedditContent
from app.models.subreddits import MonitoredSubreddit, SubredditStatus
from app.services.poller import RedditPoller


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_submission(
    post_id: str = "abc123",
    title: str = "Test Post",
    selftext: str = "This is the body",
    author: str = "testuser",
    created_utc: float = 1700000000.0,
    comments: Optional[list] = None,
):
    """Build a fake PRAW Submission-like object."""
    sub = SimpleNamespace(
        id=post_id,
        title=title,
        selftext=selftext,
        author=author,
        created_utc=created_utc,
    )
    comment_list = comments if comments is not None else []
    mock_comments = MagicMock()
    mock_comments.replace_more = MagicMock()
    mock_comments.__iter__ = lambda self: iter(comment_list)
    mock_comments.__len__ = lambda self: len(comment_list)
    sub.comments = mock_comments
    return sub


def _make_comment(
    comment_id: str = "com456",
    body: str = "Nice post!",
    author: str = "commenter",
    created_utc: float = 1700000100.0,
):
    """Build a fake PRAW Comment-like object."""
    return SimpleNamespace(
        id=comment_id,
        body=body,
        author=author,
        created_utc=created_utc,
    )


def _make_db_session(existing_hashes=None, existing_reddit_ids=None):
    """Create a mock DB session.

    Args:
        existing_hashes: Set of content_hash values already in the DB.
        existing_reddit_ids: Set of reddit_id values already in the DB.
    """
    existing_hashes = existing_hashes or set()
    existing_reddit_ids = existing_reddit_ids or set()
    session = MagicMock()

    def query_side_effect(column):
        mock_query = MagicMock()

        def filter_side_effect(condition):
            mock_filtered = MagicMock()
            # Inspect the binary expression to decide the return value
            try:
                right_val = condition.right.effective_value
            except AttributeError:
                right_val = None

            if right_val in existing_hashes or right_val in existing_reddit_ids:
                mock_filtered.first.return_value = (uuid.uuid4(),)
            else:
                mock_filtered.first.return_value = None
            return mock_filtered

        mock_query.filter.side_effect = filter_side_effect
        return mock_query

    session.query.side_effect = query_side_effect
    return session


def _make_reddit_client(submissions: Optional[list] = None):
    """Create a mock PRAW Reddit client."""
    client = MagicMock()
    subreddit_mock = MagicMock()
    subreddit_mock.new.return_value = submissions or []
    client.subreddit.return_value = subreddit_mock
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRedditPollerInit:
    def test_accepts_db_and_reddit_client(self):
        db = MagicMock()
        reddit = MagicMock()
        poller = RedditPoller(db, reddit)
        assert poller.db is db
        assert poller.reddit is reddit

    @patch.dict("os.environ", {}, clear=True)
    def test_raises_on_missing_credentials(self):
        db = MagicMock()
        with pytest.raises(RuntimeError, match="REDDIT_CLIENT_ID"):
            RedditPoller(db)

    @patch.dict(
        "os.environ",
        {
            "REDDIT_CLIENT_ID": "test_id",
            "REDDIT_CLIENT_SECRET": "test_secret",
            "REDDIT_USER_AGENT": "test_agent",
        },
    )
    @patch("app.services.poller.Reddit")
    def test_creates_client_from_env_when_none_provided(self, mock_reddit_cls):
        db = MagicMock()
        mock_reddit_cls.return_value = MagicMock()
        poller = RedditPoller(db)
        mock_reddit_cls.assert_called_once_with(
            client_id="test_id",
            client_secret="test_secret",
            user_agent="test_agent",
        )


class TestFetchPosts:
    def test_calls_subreddit_new(self):
        reddit = _make_reddit_client()
        poller = RedditPoller(MagicMock(), reddit)
        poller._fetch_posts("test_sub", 50)
        reddit.subreddit.assert_called_once_with("test_sub")
        reddit.subreddit.return_value.new.assert_called_once_with(limit=50)


class TestFetchComments:
    def test_returns_top_level_comments(self):
        comment = _make_comment()
        submission = _make_submission(comments=[comment])
        poller = RedditPoller(MagicMock(), MagicMock())
        result = poller._fetch_comments(submission)
        submission.comments.replace_more.assert_called_once_with(limit=0)
        assert len(result) == 1

    def test_empty_comments(self):
        submission = _make_submission(comments=[])
        poller = RedditPoller(MagicMock(), MagicMock())
        result = poller._fetch_comments(submission)
        assert result == []


class TestPollSubreddit:
    def test_stores_new_posts_and_comments(self):
        comment = _make_comment(comment_id="c1", body="great insight")
        submission = _make_submission(
            post_id="p1",
            title="Arbitrage Betting Tips",
            selftext="Here are some tips",
            comments=[comment],
        )
        reddit = _make_reddit_client([submission])
        db = _make_db_session()
        poller = RedditPoller(db, reddit)

        result = poller.poll_subreddit("sportsbook", limit=10)

        # Should have added records and committed
        assert db.add.call_count == 2  # 1 post + 1 comment
        db.commit.assert_called_once()
        assert len(result) == 2

    def test_skips_duplicates(self):
        submission = _make_submission(post_id="dup1", selftext="duplicate content")
        reddit = _make_reddit_client([submission])
        # Simulate hash already existing
        db = _make_db_session(existing_reddit_ids={"dup1"})
        poller = RedditPoller(db, reddit)

        result = poller.poll_subreddit("test")

        assert len(result) == 0
        db.commit.assert_not_called()

    def test_handles_empty_subreddit(self):
        reddit = _make_reddit_client([])
        db = _make_db_session()
        poller = RedditPoller(db, reddit)

        result = poller.poll_subreddit("empty_sub")

        assert result == []
        db.commit.assert_not_called()

    def test_normalizes_content_before_storage(self):
        submission = _make_submission(
            post_id="n1",
            title="Check **this** out",
            selftext="Visit https://example.com for details",
        )
        reddit = _make_reddit_client([submission])
        db = _make_db_session()
        poller = RedditPoller(db, reddit)

        result = poller.poll_subreddit("test")

        # The stored record should have normalized text (no markdown, no URLs)
        assert len(result) == 1
        record = result[0]
        assert "**" not in record.normalized_text
        assert "https://example.com" not in record.normalized_text

    def test_deleted_author_handled(self):
        submission = _make_submission(post_id="d1", author=None)
        reddit = _make_reddit_client([submission])
        db = _make_db_session()
        poller = RedditPoller(db, reddit)

        result = poller.poll_subreddit("test")

        assert len(result) == 1
        assert result[0].author == "[deleted]"


class TestPollAllActive:
    def test_polls_each_active_subreddit(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            ("sub_a",),
            ("sub_b",),
        ]
        reddit = _make_reddit_client([])
        poller = RedditPoller(db, reddit)

        with patch.object(poller, "poll_subreddit", return_value=[]) as mock_poll:
            results = poller.poll_all_active()
            assert mock_poll.call_count == 2
            mock_poll.assert_any_call("sub_a")
            mock_poll.assert_any_call("sub_b")
            assert "sub_a" in results
            assert "sub_b" in results

    def test_handles_poll_failure_gracefully(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [("bad_sub",)]
        reddit = _make_reddit_client()
        poller = RedditPoller(db, reddit)

        with patch.object(
            poller, "poll_subreddit", side_effect=Exception("API error")
        ):
            results = poller.poll_all_active()
            assert results["bad_sub"] == []

    def test_no_active_subreddits(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        reddit = _make_reddit_client()
        poller = RedditPoller(db, reddit)

        with patch.object(poller, "poll_subreddit") as mock_poll:
            results = poller.poll_all_active()
            mock_poll.assert_not_called()
            assert results == {}
