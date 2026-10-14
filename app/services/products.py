"""Products and their stock. Every function is scoped to one tenant."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select

from app.errors import ConflictError, InsufficientStockError, NotFoundError
from app.extensions import db
from app.models import MovementReason, Product, StockMovement
from app.services.common import commit_or_conflict


def _active_products(tenant_id: int) -> Select[Product]:
    """Base query: this tenant's products that are not deleted."""
    return select(Product).where(Product.tenant_id == tenant_id, Product.deleted_at.is_(None))


def _sku_taken(tenant_id: int, sku: str) -> bool:
    return db.session.scalar(_active_products(tenant_id).where(Product.sku == sku)) is not None


def _sku_conflict(sku: str) -> str:
    return f"A product with SKU {sku} already exists."


def list_products(tenant_id: int) -> list[Product]:
    return list(db.session.scalars(_active_products(tenant_id).order_by(Product.id)))


def get_product(tenant_id: int, product_id: int, *, lock: bool = False) -> Product:
    """Find one product, or raise 404 (also for other tenants' products)."""
    query = _active_products(tenant_id).where(Product.id == product_id)
    if lock:
        # SELECT ... FOR UPDATE: other requests wanting this row wait until we commit.
        # populate_existing makes sure we read the latest stock after getting the lock.
        query = query.with_for_update().execution_options(populate_existing=True)
    product = db.session.scalar(query)
    if product is None:
        raise NotFoundError(f"Product {product_id} was not found.")
    return product


def create_product(
    tenant_id: int, sku: str, name: str, price: Decimal, initial_stock: int
) -> Product:
    if _sku_taken(tenant_id, sku):
        raise ConflictError(_sku_conflict(sku))

    product = Product(tenant_id=tenant_id, sku=sku, name=name, price=price)
    db.session.add(product)
    db.session.flush()  # get product.id for the stock movement
    if initial_stock > 0:
        apply_stock_change(product, initial_stock, MovementReason.INITIAL)
    commit_or_conflict(_sku_conflict(sku))
    return product


def update_product(tenant_id: int, product_id: int, changes: dict[str, Any]) -> Product:
    product = get_product(tenant_id, product_id)
    new_sku = changes.get("sku")
    if new_sku and new_sku != product.sku and _sku_taken(tenant_id, new_sku):
        raise ConflictError(_sku_conflict(new_sku))

    for field, value in changes.items():
        setattr(product, field, value)
    commit_or_conflict(_sku_conflict(new_sku or product.sku))
    return product


def delete_product(tenant_id: int, product_id: int) -> None:
    """Soft delete: hide the product but keep the row, so old orders still make sense."""
    product = get_product(tenant_id, product_id)
    product.deleted_at = datetime.now(UTC)
    db.session.commit()


def apply_stock_change(
    product: Product, quantity: int, reason: str, order_id: int | None = None
) -> StockMovement:
    """Add a line to the stock ledger and update the product's stock_on_hand.

    The caller must hold a lock on the product (or have just created it) and commit.
    """
    new_stock = product.stock_on_hand + quantity
    if new_stock < 0:
        raise InsufficientStockError(
            f"{product.sku} has {product.stock_on_hand} in stock, cannot remove {-quantity}."
        )
    product.stock_on_hand = new_stock
    movement = StockMovement(
        tenant_id=product.tenant_id,
        product_id=product.id,
        quantity=quantity,
        reason=reason,
        order_id=order_id,
    )
    db.session.add(movement)
    return movement


def record_stock_movement(
    tenant_id: int, product_id: int, quantity: int, reason: str
) -> tuple[StockMovement, Product]:
    """Manually add or remove stock (restock or adjustment), safely under a row lock."""
    product = get_product(tenant_id, product_id, lock=True)
    movement = apply_stock_change(product, quantity, reason)
    db.session.commit()
    return movement, product


def list_stock_movements(tenant_id: int, product_id: int) -> list[StockMovement]:
    """The product's ledger, oldest first."""
    get_product(tenant_id, product_id)  # 404 if it isn't this tenant's product
    query = (
        select(StockMovement)
        .where(StockMovement.tenant_id == tenant_id, StockMovement.product_id == product_id)
        .order_by(StockMovement.id)
    )
    return list(db.session.scalars(query))
