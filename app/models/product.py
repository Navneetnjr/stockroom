from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin, TimestampMixin


class Product(TenantScopedMixin, TimestampMixin, Base):
    """Something a tenant sells."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_not_negative"),
        # Safety net: the database itself refuses negative stock
        CheckConstraint("stock_on_hand >= 0", name="stock_not_negative"),
        # A SKU is unique within a tenant, but only among products that are not deleted
        Index(
            "uq_products_tenant_id_sku_active",
            "tenant_id",
            "sku",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Fast copy of the ledger total (sum of this product's stock movements),
    # updated in the same transaction as every movement
    stock_on_hand: Mapped[int] = mapped_column(default=0, server_default="0")
    # Soft delete: set this instead of deleting the row
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
