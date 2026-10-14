from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin


class IdempotencyKey(TenantScopedMixin, Base):
    """Remembers the response to a POST sent with an Idempotency-Key header,
    so a repeat of the same request gets the same answer instead of doing the work twice."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_id_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255))
    # SHA-256 of the request, to catch a key reused for a different request
    request_hash: Mapped[str] = mapped_column(String(64))
    # Empty while the first request is still running; filled in when it succeeds
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
