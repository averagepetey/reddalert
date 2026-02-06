from __future__ import annotations

"""Data retention cleanup for Reddalert.

Removes RedditContent and Match records older than the configured retention
period to keep the database lean.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.content import RedditContent
from app.models.matches import Match

logger = logging.getLogger(__name__)


def cleanup_old_data(db_session: Session, retention_days: int = 90) -> dict:
    """Delete content and match records older than *retention_days*.

    Args:
        db_session: An active SQLAlchemy session.
        retention_days: Number of days to retain data. Records older than this
            are permanently deleted.

    Returns:
        A dict with keys: content_deleted, matches_deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Delete matches first (FK references content)
    matches_deleted = (
        db_session.query(Match)
        .filter(Match.detected_at < cutoff)
        .delete(synchronize_session="fetch")
    )

    content_deleted = (
        db_session.query(RedditContent)
        .filter(RedditContent.fetched_at < cutoff)
        .delete(synchronize_session="fetch")
    )

    db_session.commit()

    logger.info(
        "Retention cleanup: deleted %d matches and %d content items older than %d days",
        matches_deleted,
        content_deleted,
        retention_days,
    )

    return {
        "content_deleted": content_deleted,
        "matches_deleted": matches_deleted,
    }
