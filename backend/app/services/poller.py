from __future__ import annotations

"""Reddit polling service for Reddalert.

Connects to the Reddit API via PRAW, fetches new posts and top-level comments
from monitored subreddits, normalizes content, deduplicates, and persists
RedditContent records.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from praw import Reddit
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ..models.content import ContentType, RedditContent
from ..models.subreddits import MonitoredSubreddit, SubredditStatus
from .deduplicator import compute_content_hash, is_duplicate
from .normalizer import normalize_text

logger = logging.getLogger(__name__)


class RedditPoller:
    """Polls Reddit for new posts and comments, storing them as RedditContent."""

    def __init__(self, db_session: Session, reddit_client: Optional[Reddit] = None):
        """Initialize the poller.

        Args:
            db_session: Active SQLAlchemy session.
            reddit_client: Optional pre-configured PRAW Reddit instance.
                           If not provided, one is created from environment variables.
        """
        self.db = db_session
        self.reddit = reddit_client or self._create_reddit_client()

    @staticmethod
    def _create_reddit_client() -> Reddit:
        """Create a PRAW Reddit client from environment variables."""
        return Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "reddalert/1.0"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_subreddit(
        self, subreddit_name: str, limit: int = 100
    ) -> list[RedditContent]:
        """Fetch new posts and top-level comments for a single subreddit.

        Args:
            subreddit_name: Name of the subreddit (without r/ prefix).
            limit: Maximum number of posts to fetch per poll.

        Returns:
            List of newly created RedditContent records.
        """
        raw_items: list[dict] = []

        posts = self._fetch_posts(subreddit_name, limit)
        for post in posts:
            raw_items.append(
                {
                    "reddit_id": post.id,
                    "subreddit": subreddit_name,
                    "content_type": ContentType.post,
                    "title": post.title,
                    "body": post.selftext or "",
                    "author": str(post.author) if post.author else "[deleted]",
                    "reddit_created_at": datetime.fromtimestamp(
                        post.created_utc, tz=timezone.utc
                    ),
                }
            )

            comments = self._fetch_comments(post)
            for comment in comments:
                raw_items.append(
                    {
                        "reddit_id": comment.id,
                        "subreddit": subreddit_name,
                        "content_type": ContentType.comment,
                        "title": None,
                        "body": comment.body or "",
                        "author": str(comment.author) if comment.author else "[deleted]",
                        "reddit_created_at": datetime.fromtimestamp(
                            comment.created_utc, tz=timezone.utc
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

    def _fetch_posts(self, subreddit_name: str, limit: int) -> list:
        """Fetch recent posts from a subreddit via PRAW.

        Args:
            subreddit_name: Subreddit name without the r/ prefix.
            limit: Max posts to retrieve.

        Returns:
            List of PRAW Submission objects.
        """
        subreddit = self.reddit.subreddit(subreddit_name)
        return list(subreddit.new(limit=limit))

    def _fetch_comments(self, submission) -> list:
        """Fetch top-level comments from a submission.

        Args:
            submission: A PRAW Submission object.

        Returns:
            List of top-level PRAW Comment objects (MoreComments are skipped).
        """
        submission.comments.replace_more(limit=0)
        return list(submission.comments)

    def _store_content(self, raw_items: list[dict]) -> list[RedditContent]:
        """Normalize, deduplicate, and persist raw content items.

        Args:
            raw_items: List of dicts with keys matching RedditContent columns
                       plus raw text in 'title' and 'body'.

        Returns:
            List of newly created RedditContent records.
        """
        new_records: list[RedditContent] = []

        for item in raw_items:
            # Build the text to normalize: title + body for posts, body for comments
            if item["title"]:
                raw_text = f"{item['title']} {item['body']}"
            else:
                raw_text = item["body"]

            normalized = normalize_text(raw_text)
            content_hash = compute_content_hash(normalized.normalized_text)

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
