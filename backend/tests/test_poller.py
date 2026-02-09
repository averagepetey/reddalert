"""Tests for the Reddit poller service."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from app.models.content import ContentType, RedditContent
from app.models.subreddits import MonitoredSubreddit, SubredditStatus
from app.services.poller import RedditPoller


# ---------------------------------------------------------------------------
# Helpers — build Reddit-style JSON responses
# ---------------------------------------------------------------------------


def _make_post_data(
    post_id: str = "abc123",
    title: str = "Test Post",
    selftext: str = "This is the body",
    author: str = "testuser",
    created_utc: float = 1700000000.0,
) -> dict:
    """Build a dict matching a single post's ``data`` from Reddit JSON."""
    return {
        "id": post_id,
        "title": title,
        "selftext": selftext,
        "author": author,
        "created_utc": created_utc,
    }


def _make_comment_data(
    comment_id: str = "com456",
    body: str = "Nice post!",
    author: str = "commenter",
    created_utc: float = 1700000100.0,
    parent_id: str = "t3_abc123",
) -> dict:
    """Build a dict matching a single comment's ``data`` from Reddit JSON."""
    return {
        "id": comment_id,
        "body": body,
        "author": author,
        "created_utc": created_utc,
        "parent_id": parent_id,
    }


def _make_listing(children: list, kind: str = "t3") -> dict:
    """Wrap child dicts into a Reddit JSON listing envelope."""
    return {
        "kind": "Listing",
        "data": {
            "children": [{"kind": kind, "data": c} for c in children],
        },
    }


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


def _make_http_client(posts_response=None, comments_response=None):
    """Create a mock httpx.Client that returns canned JSON for posts & comments.

    Args:
        posts_response: Listing dict returned for ``/new.json``.
        comments_response: Listing dict returned for ``/comments.json``.
    """
    if posts_response is None:
        posts_response = _make_listing([])
    if comments_response is None:
        comments_response = _make_listing([], kind="t1")

    client = MagicMock(spec=httpx.Client)

    def get_side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        if "/new.json" in url:
            mock_resp.json.return_value = posts_response
        elif "/comments.json" in url:
            mock_resp.json.return_value = comments_response
        else:
            mock_resp.json.return_value = _make_listing([])
        return mock_resp

    client.get.side_effect = get_side_effect
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRedditPollerInit:
    def test_accepts_db_and_http_client(self):
        db = MagicMock()
        http = MagicMock(spec=httpx.Client)
        poller = RedditPoller(db, http)
        assert poller.db is db
        assert poller.http is http

    def test_creates_default_http_client_when_none_provided(self):
        db = MagicMock()
        with patch.object(RedditPoller, "_create_http_client") as mock_create:
            mock_create.return_value = MagicMock(spec=httpx.Client)
            poller = RedditPoller(db)
            mock_create.assert_called_once()
            assert poller.http is mock_create.return_value


class TestFetchPosts:
    def test_calls_correct_url(self):
        http = _make_http_client()
        poller = RedditPoller(MagicMock(), http)
        poller._fetch_posts("test_sub", 50)
        http.get.assert_called_once()
        url_arg = http.get.call_args[0][0]
        assert "/r/test_sub/new.json" in url_arg
        assert http.get.call_args[1]["params"]["limit"] == 50

    def test_returns_post_data_dicts(self):
        post = _make_post_data(post_id="p1", title="Hello")
        http = _make_http_client(posts_response=_make_listing([post]))
        poller = RedditPoller(MagicMock(), http)
        result = poller._fetch_posts("test_sub", 10)
        assert len(result) == 1
        assert result[0]["id"] == "p1"
        assert result[0]["title"] == "Hello"


class TestFetchComments:
    def test_returns_top_level_comments_only(self):
        top_level = _make_comment_data(comment_id="c1", parent_id="t3_post1")
        reply = _make_comment_data(comment_id="c2", parent_id="t1_c1")
        listing = _make_listing([top_level, reply], kind="t1")
        http = _make_http_client(comments_response=listing)
        poller = RedditPoller(MagicMock(), http)
        result = poller._fetch_comments("test_sub")
        assert len(result) == 1
        assert result[0]["id"] == "c1"

    def test_empty_comments(self):
        http = _make_http_client(comments_response=_make_listing([], kind="t1"))
        poller = RedditPoller(MagicMock(), http)
        result = poller._fetch_comments("test_sub")
        assert result == []


class TestPollSubreddit:
    @patch("app.services.poller.time.sleep")
    def test_stores_new_posts_and_comments(self, mock_sleep):
        post = _make_post_data(
            post_id="p1",
            title="Arbitrage Betting Tips",
            selftext="Here are some tips",
        )
        comment = _make_comment_data(
            comment_id="c1", body="great insight", parent_id="t3_p1"
        )
        http = _make_http_client(
            posts_response=_make_listing([post]),
            comments_response=_make_listing([comment], kind="t1"),
        )
        db = _make_db_session()
        poller = RedditPoller(db, http)

        result = poller.poll_subreddit("sportsbook", limit=10)

        # Should have added records and committed
        assert db.add.call_count == 2  # 1 post + 1 comment
        db.commit.assert_called_once()
        assert len(result) == 2

    @patch("app.services.poller.time.sleep")
    def test_skips_duplicates(self, mock_sleep):
        post = _make_post_data(post_id="dup1", selftext="duplicate content")
        http = _make_http_client(posts_response=_make_listing([post]))
        # Simulate reddit_id already existing
        db = _make_db_session(existing_reddit_ids={"dup1"})
        poller = RedditPoller(db, http)

        result = poller.poll_subreddit("test")

        assert len(result) == 0
        db.commit.assert_not_called()

    @patch("app.services.poller.time.sleep")
    def test_handles_empty_subreddit(self, mock_sleep):
        http = _make_http_client()
        db = _make_db_session()
        poller = RedditPoller(db, http)

        result = poller.poll_subreddit("empty_sub")

        assert result == []
        db.commit.assert_not_called()

    @patch("app.services.poller.time.sleep")
    def test_normalizes_content_before_storage(self, mock_sleep):
        post = _make_post_data(
            post_id="n1",
            title="Check **this** out",
            selftext="Visit https://example.com for details",
        )
        http = _make_http_client(posts_response=_make_listing([post]))
        db = _make_db_session()
        poller = RedditPoller(db, http)

        result = poller.poll_subreddit("test")

        # The stored record should have normalized text (no markdown, no URLs)
        assert len(result) == 1
        record = result[0]
        assert "**" not in record.normalized_text
        assert "https://example.com" not in record.normalized_text

    @patch("app.services.poller.time.sleep")
    def test_deleted_author_handled(self, mock_sleep):
        post = _make_post_data(post_id="d1")
        post["author"] = None
        http = _make_http_client(posts_response=_make_listing([post]))
        db = _make_db_session()
        poller = RedditPoller(db, http)

        result = poller.poll_subreddit("test")

        assert len(result) == 1
        assert result[0].author == "[deleted]"

    @patch("app.services.poller.time.sleep")
    def test_sleeps_between_posts_and_comments_requests(self, mock_sleep):
        http = _make_http_client()
        db = _make_db_session()
        poller = RedditPoller(db, http)
        poller.poll_subreddit("test")
        mock_sleep.assert_called_once()


class TestPollAllActive:
    def test_polls_each_active_subreddit(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            ("sub_a",),
            ("sub_b",),
        ]
        http = _make_http_client()
        poller = RedditPoller(db, http)

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
        http = _make_http_client()
        poller = RedditPoller(db, http)

        with patch.object(
            poller, "poll_subreddit", side_effect=Exception("API error")
        ):
            results = poller.poll_all_active()
            assert results["bad_sub"] == []

    def test_no_active_subreddits(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        http = _make_http_client()
        poller = RedditPoller(db, http)

        with patch.object(poller, "poll_subreddit") as mock_poll:
            results = poller.poll_all_active()
            mock_poll.assert_not_called()
            assert results == {}
