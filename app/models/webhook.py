from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin


class DeliveryStatus(StrEnum):
    PENDING = "pending"  # not delivered yet (waiting for the first try or a retry)
    DELIVERED = "delivered"
    DEAD = "dead"  # gave up after the maximum attempts; copied to webhook_dead_letters


class WebhookDelivery(TenantScopedMixin, Base):
    """One event to send to a tenant's webhook URL, and how sending it went.

    The row is written in the same transaction as the order change, so an event can't be
    lost even if the queue is briefly unavailable (it stays here as pending).
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'delivered', 'dead')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique id the receiver can use to ignore duplicates
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDeadLetter(TenantScopedMixin, Base):
    """A webhook that could not be delivered after the maximum attempts, kept for follow-up."""

    __tablename__ = "webhook_dead_letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("webhook_deliveries.id"), unique=True)
    event_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target_url: Mapped[str] = mapped_column(String(500))
    attempts: Mapped[int]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
