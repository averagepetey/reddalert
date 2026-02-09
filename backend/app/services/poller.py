from __future__ import annotations

"""Reddit polling service for Reddalert.

Fetches new posts and top-level comments from monitored subreddits using
Reddit's public JSON endpoints (no API credentials required), normalizes
content, deduplicates, and persists RedditContent records.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ..models.content import ContentType, RedditContent
from ..models.subreddits import MonitoredSubreddit, SubredditStatus
from .deduplicator import compute_content_hash, is_duplicate
from .normalizer import normalize_text

logger = logging.getLogger(__name__)

REDDIT_BASE_URL = "https://www.reddit.com"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Reddalert/1.0)"
# Small delay between the posts and comments requests to stay under rate limits.
REQUEST_DELAY = 1.0


class RedditPoller:
    """Polls Reddit for new posts and comments, storing them as RedditContent."""

    def __init__(
        self, db_session: Session, http_client: Optional[httpx.Client] = None
    ):
        """Initialize the poller.

        Args:
            db_session: Active SQLAlchemy session.
            http_client: Optional pre-configured httpx.Client.
                         If not provided, one is created with a default User-Agent.
        """
        self.db = db_session
        self.http = http_client or self._create_http_client()

    @staticmethod
    def _create_http_client() -> httpx.Client:
        """Create an httpx client for Reddit's public JSON endpoints."""
        return httpx.Client(
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_subreddit(
        self, subreddit_name: str, limit: int = 100
    ) -> list[RedditContent]:
        """Fetch new posts and top-level comments for a single subreddit.

        Makes two requests per subreddit:
          1. /r/{sub}/new.json      — recent posts
          2. /r/{sub}/comments.json — recent top-level comments

        Args:
            subreddit_name: Name of the subreddit (without r/ prefix).
            limit: Maximum number of items to fetch per endpoint.

        Returns:
            List of newly created RedditContent records.
        """
        raw_items: list[dict] = []

        posts = self._fetch_posts(subreddit_name, limit)
        for post in posts:
            raw_items.append(
                {
                    "reddit_id": post["id"],
                    "subreddit": subreddit_name,
                    "content_type": ContentType.post,
                    "title": post.get("title", ""),
                    "body": post.get("selftext", ""),
                    "author": post.get("author") or "[deleted]",
                    "reddit_created_at": datetime.fromtimestamp(
                        post["created_utc"], tz=timezone.utc
                    ),
                }
            )

        time.sleep(REQUEST_DELAY)

        comments = self._fetch_comments(subreddit_name, limit)
        for comment in comments:
            raw_items.append(
                {
                    "reddit_id": comment["id"],
                    "subreddit": subreddit_name,
                    "content_type": ContentType.comment,
                    "title": None,
                    "body": comment.get("body", ""),
                    "author": comment.get("author") or "[deleted]",
                    "reddit_created_at": datetime.fromtimestamp(
                        comment["created_utc"], tz=timezone.utc
                    ),
                }
            )

        return self._store_content(raw_items)

    def poll_all_active(self) -> dict[str, list[RedditContent]]:
        """Poll every subreddit that has at least one active monitor.

        Returns:
            Dict mapping subreddit name to list of new RedditContent records.
        """
        active_names = (
            self.db.query(distinct(MonitoredSubreddit.name))
            .filter(MonitoredSubreddit.status == SubredditStatus.active)
            .all()
        )

        results: dict[str, list[RedditContent]] = {}
        for (name,) in active_names:
            try:
                new_content = self.poll_subreddit(name)
                results[name] = new_content
            except Exception:
                logger.exception("Failed to poll r/%s", name)
                results[name] = []

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_posts(self, subreddit_name: str, limit: int) -> list[dict]:
        """Fetch recent posts from a subreddit via its public JSON feed.

        Args:
            subreddit_name: Subreddit name without the r/ prefix.
            limit: Max posts to retrieve.

        Returns:
            List of post data dicts from the Reddit JSON response.
        """
        url = f"{REDDIT_BASE_URL}/r/{subreddit_name}/new.json"
        resp = self.http.get(url, params={"limit": limit, "raw_json": 1})
        resp.raise_for_status()
        data = resp.json()
        return [child["data"] for child in data["data"]["children"]]

    def _fetch_comments(self, subreddit_name: str, limit: int = 100) -> list[dict]:
        """Fetch recent top-level comments from a subreddit.

        Uses /r/{sub}/comments.json which returns the latest comments across
        the entire subreddit in a single request. Filters to top-level only
        (parent_id starts with ``t3_``).

        Args:
            subreddit_name: Subreddit name without the r/ prefix.
            limit: Max comments to retrieve.

        Returns:
            List of comment data dicts (top-level only).
        """
        url = f"{REDDIT_BASE_URL}/r/{subreddit_name}/comments.json"
        resp = self.http.get(url, params={"limit": limit, "raw_json": 1})
        resp.raise_for_status()
        data = resp.json()

        comments: list[dict] = []
        for child in data["data"]["children"]:
            if child["kind"] == "t1":
                comment_data = child["data"]
                # Top-level comments have a link (t3_) as their parent
                if comment_data.get("parent_id", "").startswith("t3_"):
                    comments.append(comment_data)
        return comments

    def _store_content(self, raw_items: list[dict]) -> list[RedditContent]:
        """Normalize, deduplicate, and persist raw content items.

        Args:
            raw_items: List of dicts with keys matching RedditContent columns
                       plus raw text in 'title' and 'body'.

        Returns:
            List of newly created RedditContent records.
        """
        new_records: list[RedditContent] = []
        seen_hashes: set[str] = set()

        for item in raw_items:
            # Build the text to normalize: title + body for posts, body for comments
            if item["title"]:
                raw_text = f"{item['title']} {item['body']}"
            else:
                raw_text = item["body"]

            normalized = normalize_text(raw_text)
            content_hash = compute_content_hash(normalized.normalized_text)

            # Skip duplicates within this batch
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            if is_duplicate(self.db, content_hash):
                continue

            # Also skip if reddit_id already stored (safety net)
            existing = (
                self.db.query(RedditContent.id)
                .filter(RedditContent.reddit_id == item["reddit_id"])
                .first()
            )
            if existing:
                continue

            record = RedditContent(
                reddit_id=item["reddit_id"],
                subreddit=item["subreddit"],
                content_type=item["content_type"],
                title=item["title"],
                body=item["body"],
                author=item["author"],
                normalized_text=normalized.normalized_text,
                content_hash=content_hash,
                reddit_created_at=item["reddit_created_at"],
            )
            self.db.add(record)
            new_records.append(record)

        if new_records:
            self.db.commit()

        return new_records
