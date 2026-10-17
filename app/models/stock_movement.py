from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Connection, DateTime, ForeignKey, String, event, func
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin


class MovementReason(StrEnum):
    INITIAL = "initial"  # starting stock when a product is created
    RESTOCK = "restock"  # new stock arrived
    ORDER_PLACED = "order_placed"  # stock sold (negative quantity)
    ORDER_CANCELLED = "order_cancelled"  # stock returned when an order is cancelled
    ADJUSTMENT = "adjustment"  # manual correction, e.g. damaged items
    IMPORT = "import"  # stock set by a CSV import


class StockMovement(TenantScopedMixin, Base):
    """One line in the stock ledger (the stock notebook).

    Rows are only ever inserted, never updated or deleted.
    A product's real stock is the SUM(quantity) of its movements.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_not_zero"),
        CheckConstraint(
            "reason IN ('initial', 'restock', 'order_placed', 'order_cancelled', "
            "'adjustment', 'import')",
            name="reason_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int]  # positive = stock in, negative = stock out
    reason: Mapped[str] = mapped_column(String(30))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@event.listens_for(StockMovement, "before_update")
@event.listens_for(StockMovement, "before_delete")
def _block_changes(mapper: Mapper[Any], connection: Connection, target: StockMovement) -> None:
    """Keep the ledger append-only: refuse to update or delete a movement through the ORM."""
    raise ValueError("Stock movements are append-only: insert a new movement instead.")
