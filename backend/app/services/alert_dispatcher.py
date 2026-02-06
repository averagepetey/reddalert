"""Alert dispatcher for Reddalert.

Pulls pending matches, batches them per client, formats Discord-rich embeds,
and delivers them via Discord webhooks with retry logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.models.clients import Client
from app.models.matches import AlertStatus, Match
from app.models.webhooks import WebhookConfig

logger = logging.getLogger(__name__)

BATCH_THRESHOLD = 3
BATCH_WINDOW_SECONDS = 120  # 2 minutes
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # seconds


@dataclass
class AlertBatch:
    """A group of matches destined for a single Discord webhook."""
    client_id: UUID
    webhook_url: str
    matches: list[Match] = field(default_factory=list)
    is_batch: bool = False


class AlertDispatcher:
    """Sends Discord alerts for pending matches."""

    def __init__(self, db_session: Session) -> None:
        self.db = db_session

    def dispatch_pending(self) -> dict:
        """Find pending matches, batch them, send alerts, and return a summary.

        Returns a dict with keys: sent, failed, total.
        """
        pending = self._get_pending_matches()
        if not pending:
            return {"sent": 0, "failed": 0, "total": 0}

        batches = self._batch_matches(pending)

        sent = 0
        failed = 0

        for batch in batches:
            if batch.is_batch:
                payload = self._format_batch_embed(batch.matches)
            else:
                payload = self._format_embed(batch.matches[0])

            success = self._send_webhook(batch.webhook_url, payload)

            now = datetime.now(timezone.utc)
            for match in batch.matches:
                if success:
                    match.alert_status = AlertStatus.sent
                    match.alert_sent_at = now
                    sent += 1
                else:
                    self._handle_failure(match)
                    failed += 1

        self.db.commit()
        return {"sent": sent, "failed": failed, "total": len(pending)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_pending_matches(self) -> list[Match]:
        """Query matches with alert_status = pending."""
        return (
            self.db.query(Match)
            .filter(Match.alert_status == AlertStatus.pending)
            .order_by(Match.detected_at)
            .all()
        )

    def _batch_matches(self, matches: list[Match]) -> list[AlertBatch]:
        """Group matches by client and apply the 2-minute batching rule.

        If a client has >= BATCH_THRESHOLD matches whose detected_at timestamps
        all fall within a BATCH_WINDOW_SECONDS window, they are sent as a
        single batched embed.  Otherwise each match is dispatched individually.
        """
        # Group by client_id
        by_client: dict[UUID, list[Match]] = {}
        for m in matches:
            by_client.setdefault(m.client_id, []).append(m)

        batches: list[AlertBatch] = []

        for client_id, client_matches in by_client.items():
            webhook_url = self._get_webhook_url(client_id)
            if not webhook_url:
                logger.warning("No active webhook for client %s — skipping", client_id)
                continue

            # Check batching condition
            if len(client_matches) >= BATCH_THRESHOLD:
                timestamps = [m.detected_at for m in client_matches]
                min_ts = min(timestamps)
                max_ts = max(timestamps)
                window = timedelta(seconds=BATCH_WINDOW_SECONDS)

                if (max_ts - min_ts) <= window:
                    batches.append(AlertBatch(
                        client_id=client_id,
                        webhook_url=webhook_url,
                        matches=client_matches,
                        is_batch=True,
                    ))
                    continue

            # Send individually
            for m in client_matches:
                batches.append(AlertBatch(
                    client_id=client_id,
                    webhook_url=webhook_url,
                    matches=[m],
                    is_batch=False,
                ))

        return batches

    def _get_webhook_url(self, client_id: UUID) -> str | None:
        """Return the primary active webhook URL for a client."""
        wh = (
            self.db.query(WebhookConfig)
            .filter(
                WebhookConfig.client_id == client_id,
                WebhookConfig.is_active.is_(True),
                WebhookConfig.is_primary.is_(True),
            )
            .first()
        )
        if wh:
            return wh.url
        # Fallback: any active webhook for this client
        wh = (
            self.db.query(WebhookConfig)
            .filter(
                WebhookConfig.client_id == client_id,
                WebhookConfig.is_active.is_(True),
            )
            .first()
        )
        return wh.url if wh else None

    # ------------------------------------------------------------------
    # Discord embed formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_embed(match: Match) -> dict:
        """Create a Discord embed payload for a single match."""
        description = match.snippet or ""
        if len(description) > 200:
            description = description[:197] + "..."

        embed: dict = {
            "title": f"Keyword Match in r/{match.subreddit}",
            "description": description,
            "url": match.reddit_url,
            "color": 0xFF4500,  # Reddit orange
            "fields": [
                {"name": "Keyword", "value": match.matched_phrase, "inline": True},
                {"name": "Subreddit", "value": f"r/{match.subreddit}", "inline": True},
                {"name": "Author", "value": f"u/{match.reddit_author}", "inline": True},
            ],
            "footer": {"text": "Reddalert"},
        }

        if match.also_matched:
            embed["fields"].append({
                "name": "Also Matched",
                "value": ", ".join(match.also_matched),
                "inline": False,
            })

        return {"embeds": [embed]}

    @staticmethod
    def _format_batch_embed(matches: list[Match]) -> dict:
        """Create a batched Discord embed payload for multiple matches."""
        first = matches[0]

        fields: list[dict] = []
        for m in matches:
            snippet = (m.snippet or "")[:100]
            fields.append({
                "name": f"{m.matched_phrase} in r/{m.subreddit}",
                "value": f"{snippet}\n[View post]({m.reddit_url})",
                "inline": False,
            })

        embed: dict = {
            "title": f"{len(matches)} New Keyword Matches",
            "description": f"Batch alert — {len(matches)} matches detected recently.",
            "color": 0xFF4500,
            "fields": fields,
            "footer": {"text": "Reddalert"},
        }

        return {"embeds": [embed]}

    # ------------------------------------------------------------------
    # Webhook delivery with retry
    # ------------------------------------------------------------------

    def _send_webhook(self, webhook_url: str, payload: dict) -> bool:
        """POST payload to Discord webhook with exponential-backoff retry.

        Returns True on success, False after MAX_RETRIES failures.
        """
        import time

        backoff = INITIAL_BACKOFF
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(webhook_url, json=payload)
                    if resp.status_code in (200, 204):
                        return True
                    logger.warning(
                        "Webhook returned %d on attempt %d/%d",
                        resp.status_code, attempt, MAX_RETRIES,
                    )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Webhook request failed on attempt %d/%d: %s",
                    attempt, MAX_RETRIES, exc,
                )

            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2

        return False

    def _handle_failure(self, match: Match) -> None:
        """Mark a match as failed after retries are exhausted, then attempt email fallback."""
        match.alert_status = AlertStatus.failed
        logger.error(
            "Alert delivery failed for match %s (keyword=%s, subreddit=%s)",
            match.id, match.matched_phrase, match.subreddit,
        )

        # Attempt email fallback to the client's registered email
        client = self.db.query(Client).filter(Client.id == match.client_id).first()
        if client and client.email:
            self._send_failure_email(
                to_email=client.email,
                match=match,
            )
        else:
            logger.warning(
                "No email on file for client %s — cannot send failure notification",
                match.client_id,
            )

    @staticmethod
    def _send_failure_email(to_email: str, match: Match) -> None:
        """Send a failure notification email when webhook delivery fails.

        This is a stub — replace with real SMTP or SendGrid integration.
        """
        logger.info(
            "EMAIL STUB: Would send failure notification to %s for match %s "
            "(phrase=%s, subreddit=r/%s, url=%s)",
            to_email,
            match.id,
            match.matched_phrase,
            match.subreddit,
            match.reddit_url,
        )
