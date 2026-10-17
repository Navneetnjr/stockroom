from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base
from app.models.mixins import TenantScopedMixin, TimestampMixin


class OrderStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(TenantScopedMixin, TimestampMixin, Base):
    """A customer's purchase. Its lines say which products and how many."""

    __tablename__ = "orders"  # "order" is a reserved word in SQL
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'shipped', 'delivered', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("total >= 0", name="total_not_negative"),
        # Serves the order list: one tenant's orders, newest first, page by page (cursor)
        Index("ix_orders_tenant_id_created_at_id", "tenant_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.DRAFT)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", order_by="OrderLine.id")


class OrderLine(TenantScopedMixin, Base):
    """One line of an order, e.g. "2 x Red Shoes at 499.00 each"."""

    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int]
    # Copied from the product when the order is placed,
    # so later price changes don't alter old orders
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    order: Mapped[Order] = relationship(back_populates="lines")
