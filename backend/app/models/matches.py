import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from .base import Base, UUIDPrimaryKeyMixin
from .content import ContentType


class AlertStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class Match(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "matches"

    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    keyword_id = Column(UUID(as_uuid=True), ForeignKey("keywords.id"), nullable=False)
    content_id = Column(UUID(as_uuid=True), ForeignKey("reddit_content.id"), nullable=False)
    content_type = Column(
        Enum(ContentType, name="content_type", create_type=False),
        nullable=False,
    )
    subreddit = Column(String, nullable=False, index=True)
    matched_phrase = Column(String, nullable=False)
    also_matched = Column(ARRAY(String), default=list)
    snippet = Column(String(200), nullable=False)
    full_text = Column(Text, nullable=False)
    proximity_score = Column(Float, nullable=True)
    reddit_url = Column(String, nullable=False)
    reddit_author = Column(String, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    detected_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    alert_sent_at = Column(DateTime(timezone=True), nullable=True)
    alert_status = Column(
        Enum(AlertStatus, name="alert_status"),
        default=AlertStatus.pending,
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    client = relationship("Client", back_populates="matches")
    keyword = relationship("Keyword", back_populates="matches")
    content = relationship("RedditContent", back_populates="matches")
