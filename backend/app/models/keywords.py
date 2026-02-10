from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy import String
from sqlalchemy.orm import relationship

from .base import Base, UUIDPrimaryKeyMixin


class Keyword(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "keywords"

    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    phrases = Column(ARRAY(String), nullable=False)
    exclusions = Column(ARRAY(String), default=list)
    proximity_window = Column(Integer, default=15, nullable=False)
    require_order = Column(Boolean, default=False, nullable=False)
    use_stemming = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    silenced_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    client = relationship("Client", back_populates="keywords")
    matches = relationship("Match", back_populates="keyword", cascade="all, delete-orphan")
