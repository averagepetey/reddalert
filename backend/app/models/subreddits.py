import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SubredditStatus(str, enum.Enum):
    active = "active"
    inaccessible = "inaccessible"
    private = "private"


class MonitoredSubreddit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitored_subreddits"

    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(
        Enum(SubredditStatus, name="subreddit_status"),
        default=SubredditStatus.active,
        nullable=False,
    )
    include_media_posts = Column(Boolean, default=True, nullable=False)
    dedupe_crossposts = Column(Boolean, default=True, nullable=False)
    filter_bots = Column(Boolean, default=False, nullable=False)
    last_polled_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("Client", back_populates="monitored_subreddits")
