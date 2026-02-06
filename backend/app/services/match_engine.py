"""Match engine for Reddalert.

Takes new RedditContent records, runs them against all relevant client
keywords using the proximity matcher, and creates Match records in the
database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.clients import Client
from app.models.content import RedditContent
from app.models.keywords import Keyword
from app.models.matches import AlertStatus, Match
from app.models.subreddits import MonitoredSubreddit
from app.services.matcher import KeywordConfig, MatchResult, find_matches
from app.services.normalizer import NormalizedResult

logger = logging.getLogger(__name__)


class MatchEngine:
    """Runs new content against client keywords and persists matches."""

    def __init__(self, db_session: Session) -> None:
        self.db = db_session

    def process_content(self, content: RedditContent) -> list[Match]:
        """Run a single piece of content against all relevant keywords.

        Returns a list of newly created Match records.
        """
        relevant = self._get_relevant_keywords(content.subreddit)
        if not relevant:
            return []

        normalized = NormalizedResult(
            normalized_text=content.normalized_text,
            tokens=content.normalized_text.split() if content.normalized_text else [],
            sentences=[],
        )

        # Collect all match results grouped by client so we can populate
        # also_matched across keywords for the same client.
        client_matches: dict[str, list[tuple[Keyword, MatchResult]]] = {}

        for client, keyword in relevant:
            config = self._keyword_to_config(keyword)
            results = find_matches(normalized, config)
            if results:
                client_key = str(client.id)
                if client_key not in client_matches:
                    client_matches[client_key] = []
                for r in results:
                    client_matches[client_key].append((keyword, r))

        created: list[Match] = []

        for client_key, kw_results in client_matches.items():
            # Determine also_matched per client: collect all distinct matched
            # phrases across keywords.
            all_phrases = list({r.matched_phrase for _, r in kw_results})

            for keyword, match_result in kw_results:
                also = [p for p in all_phrases if p != match_result.matched_phrase]

                # Look up the client from the first pair (all share the same
                # client within a client_key group).
                client = keyword.client

                match_record = self._create_match_record(
                    client=client,
                    keyword=keyword,
                    content=content,
                    match_result=match_result,
                    also_matched=also,
                )
                created.append(match_record)

        if created:
            self.db.commit()
            logger.info("Created %d match(es) for content %s", len(created), content.reddit_id)

        return created

    def process_batch(self, content_list: list[RedditContent]) -> list[Match]:
        """Process multiple content items and return all created matches."""
        all_matches: list[Match] = []
        for content in content_list:
            matches = self.process_content(content)
            all_matches.extend(matches)
        return all_matches

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_relevant_keywords(self, subreddit: str) -> list[tuple[Client, Keyword]]:
        """Find all active client/keyword pairs monitoring the given subreddit."""
        monitored = (
            self.db.query(MonitoredSubreddit)
            .filter(
                MonitoredSubreddit.name == subreddit,
                MonitoredSubreddit.status == "active",
            )
            .all()
        )

        pairs: list[tuple[Client, Keyword]] = []
        for sub in monitored:
            client = sub.client
            keywords = (
                self.db.query(Keyword)
                .filter(
                    Keyword.client_id == client.id,
                    Keyword.is_active.is_(True),
                )
                .all()
            )
            for kw in keywords:
                pairs.append((client, kw))

        return pairs

    @staticmethod
    def _keyword_to_config(keyword: Keyword) -> KeywordConfig:
        """Convert a Keyword DB model to a matcher KeywordConfig dataclass.

        The DB stores phrases as a flat list of strings (each string may
        contain multiple words representing a phrase).  The matcher expects
        phrases as ``list[list[str]]`` where each inner list is the tokens
        of one phrase.
        """
        phrases = [p.split() for p in (keyword.phrases or [])]
        return KeywordConfig(
            phrases=phrases,
            exclusions=keyword.exclusions or [],
            proximity_window=keyword.proximity_window,
            require_order=keyword.require_order,
            use_stemming=keyword.use_stemming,
        )

    def _create_match_record(
        self,
        client: Client,
        keyword: Keyword,
        content: RedditContent,
        match_result: MatchResult,
        also_matched: list[str] | None = None,
    ) -> Match:
        """Persist a Match record to the database."""
        reddit_url = f"https://reddit.com/r/{content.subreddit}/comments/{content.reddit_id}"

        match = Match(
            client_id=client.id,
            keyword_id=keyword.id,
            content_id=content.id,
            content_type=content.content_type,
            subreddit=content.subreddit,
            matched_phrase=match_result.matched_phrase,
            also_matched=also_matched or [],
            snippet=match_result.snippet[:200],
            full_text=content.body or "",
            proximity_score=match_result.proximity_score,
            reddit_url=reddit_url,
            reddit_author=content.author,
            is_deleted=content.is_deleted,
            detected_at=datetime.now(timezone.utc),
            alert_status=AlertStatus.pending,
        )
        self.db.add(match)
        return match
