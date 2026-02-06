import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, UUIDPrimaryKeyMixin


class ContentType(str, enum.Enum):
    post = "post"
    comment = "comment"


class RedditContent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "reddit_content"

    reddit_id = Column(String, unique=True, nullable=False, index=True)
    subreddit = Column(String, nullable=False, index=True)
    content_type = Column(
        Enum(ContentType, name="content_type"),
        nullable=False,
    )
    title = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    author = Column(String, nullable=False)
    normalized_text = Column(Text, nullable=False)
    content_hash = Column(String, unique=True, nullable=False, index=True)
    reddit_created_at = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_deleted = Column(Boolean, default=False, nullable=False)

    matches = relationship("Match", back_populates="content")
