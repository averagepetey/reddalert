import re
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..models.clients import Client
from ..models.webhooks import WebhookConfig

_DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)

_MAX_DURATION = timedelta(days=30)

_UNIT_MAP = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse a human-readable duration string into a timedelta.

    Supports formats like ``20m``, ``2h``, ``1d``, ``30s``.
    Maximum duration is 30 days.  Returns ``None`` for invalid input.
    """
    match = _DURATION_RE.match(text.strip())
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if amount <= 0:
        return None

    td = timedelta(**{_UNIT_MAP[unit]: amount})
    if td > _MAX_DURATION:
        return None

    return td


def get_client_for_guild(db: Session, guild_id: str) -> Optional[Client]:
    """Look up the Client that owns the webhook for a given Discord guild."""
    webhook = (
        db.query(WebhookConfig)
        .filter(
            WebhookConfig.guild_id == guild_id,
            WebhookConfig.is_active.is_(True),
        )
        .first()
    )
    if webhook is None:
        return None
    return webhook.client
