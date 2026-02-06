"""Deduplication logic for Reddit content.

Provides hash-based deduplication to prevent storing duplicate content.
Called by the poller before persisting new RedditContent records.
"""

import hashlib

from sqlalchemy.orm import Session

from ..models.content import RedditContent


def compute_content_hash(normalized_text: str) -> str:
    """Compute a SHA-256 hash of normalized text for deduplication.

    Args:
        normalized_text: Text that has already been run through the normalizer.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def is_duplicate(db_session: Session, content_hash: str) -> bool:
    """Check whether a content hash already exists in the database.

    Args:
        db_session: Active SQLAlchemy session.
        content_hash: SHA-256 hex digest to check.

    Returns:
        True if a record with this hash already exists.
    """
    return (
        db_session.query(RedditContent.id)
        .filter(RedditContent.content_hash == content_hash)
        .first()
        is not None
    )


def mark_deleted(db_session: Session, reddit_id: str) -> bool:
    """Mark a piece of content as deleted if its source was removed from Reddit.

    Args:
        db_session: Active SQLAlchemy session.
        reddit_id: The Reddit ID of the post or comment.

    Returns:
        True if a matching record was found and updated, False otherwise.
    """
    record = (
        db_session.query(RedditContent)
        .filter(RedditContent.reddit_id == reddit_id)
        .first()
    )
    if record is None:
        return False
    record.is_deleted = True
    db_session.commit()
    return True
