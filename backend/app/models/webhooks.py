from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_configs"

    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    url = Column(String, nullable=False)
    guild_name = Column(String, nullable=True)
    is_primary = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("Client", back_populates="webhook_configs")
