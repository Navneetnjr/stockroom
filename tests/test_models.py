from datetime import UTC, datetime
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import MovementReason, Product, StockMovement, Tenant


def _make_tenant() -> Tenant:
    tenant = Tenant(name="Shoe Shop")
    db.session.add(tenant)
    db.session.flush()  # send the INSERT now so tenant.id gets a value
    return tenant


def _make_product(tenant: Tenant, sku: str = "RED-SHOE") -> Product:
    product = Product(tenant_id=tenant.id, sku=sku, name="Red Shoe", price=Decimal("499.00"))
    db.session.add(product)
    db.session.flush()
    return product


def test_database_refuses_negative_stock(app: Flask) -> None:
    with app.app_context():
        product = _make_product(_make_tenant())

        product.stock_on_hand = -1

        with pytest.raises(IntegrityError, match="ck_products_stock_not_negative"):
            db.session.flush()


def test_sku_is_unique_per_tenant_but_reusable_after_soft_delete(app: Flask) -> None:
    with app.app_context():
        tenant = _make_tenant()
        first = _make_product(tenant)

        # A second active product with the same SKU is refused...
        with pytest.raises(IntegrityError, match="uq_products_tenant_id_sku_active"):
            with db.session.begin_nested():
                _make_product(tenant)

        # ...but after soft-deleting the first one, the SKU can be used again
        first.deleted_at = datetime.now(UTC)
        db.session.flush()
        assert _make_product(tenant).id != first.id


def test_stock_movements_cannot_be_changed(app: Flask) -> None:
    with app.app_context():
        product = _make_product(_make_tenant())
        movement = StockMovement(
            tenant_id=product.tenant_id,
            product_id=product.id,
            quantity=10,
            reason=MovementReason.INITIAL,
        )
        db.session.add(movement)
        db.session.flush()

        movement.quantity = 5

        with pytest.raises(ValueError, match="append-only"):
            db.session.flush()
