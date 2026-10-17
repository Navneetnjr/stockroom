from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column


class TenantScopedMixin:
    """Adds tenant_id: the tenant (shop) a row belongs to.

    Every table except `tenants` uses this, so every query can be filtered by tenant.
    """

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)


class TimestampMixin:
    """Adds created_at and updated_at, filled in automatically."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), sort_order=101
    )
