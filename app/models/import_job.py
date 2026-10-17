from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin, TimestampMixin


class ImportStatus(StrEnum):
    PENDING = "pending"  # waiting for a worker
    PROCESSING = "processing"
    COMPLETED = "completed"  # finished; some rows may still have failed (see errors)
    FAILED = "failed"  # the file as a whole could not be processed


class ImportJob(TenantScopedMixin, TimestampMixin, Base):
    """A CSV product import that runs in the background."""

    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default=ImportStatus.PENDING)
    filename: Mapped[str] = mapped_column(String(255))
    # The uploaded file itself: the API and the worker are separate machines,
    # so the file travels through the database rather than a local disk
    csv_text: Mapped[str] = mapped_column(Text)
    total_rows: Mapped[int] = mapped_column(default=0)
    succeeded_rows: Mapped[int] = mapped_column(default=0)
    failed_rows: Mapped[int] = mapped_column(default=0)
    # One entry per failed row: {"row": 7, "sku": "X", "error": "price: Not a valid number."}
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
