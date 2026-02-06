from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from .base import Base, UUIDPrimaryKeyMixin


class Client(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "clients"

    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    polling_interval = Column(Integer, default=60, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    keywords = relationship("Keyword", back_populates="client", cascade="all, delete-orphan")
    monitored_subreddits = relationship(
        "MonitoredSubreddit", back_populates="client", cascade="all, delete-orphan"
    )
    webhook_configs = relationship(
        "WebhookConfig", back_populates="client", cascade="all, delete-orphan"
    )
    matches = relationship("Match", back_populates="client", cascade="all, delete-orphan")
