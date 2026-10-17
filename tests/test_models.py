from datetime import UTC, datetime

import pytest
from flask import Flask
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import MovementReason, StockMovement
from tests.factories import make_product, make_tenant


def test_database_refuses_negative_stock(app: Flask) -> None:
    with app.app_context():
        product = make_product()

        product.stock_on_hand = -1

        with pytest.raises(IntegrityError, match="ck_products_stock_not_negative"):
            db.session.flush()


def test_sku_is_unique_per_tenant_but_reusable_after_soft_delete(app: Flask) -> None:
    with app.app_context():
        tenant = make_tenant()
        first = make_product(tenant=tenant, sku="RED-SHOE")

        # A second active product with the same SKU is refused...
        with pytest.raises(IntegrityError, match="uq_products_tenant_id_sku_active"):
            make_product(tenant=tenant, sku="RED-SHOE")
        db.session.rollback()

        # ...but after soft-deleting the first one, the SKU can be used again
        first.deleted_at = datetime.now(UTC)
        db.session.commit()
        assert make_product(tenant=tenant, sku="RED-SHOE").id != first.id


def test_same_sku_is_fine_in_another_tenant(app: Flask) -> None:
    with app.app_context():
        make_product(sku="RED-SHOE")

        assert make_product(sku="RED-SHOE").sku == "RED-SHOE"  # a different new tenant


def test_stock_movements_cannot_be_changed(app: Flask) -> None:
    with app.app_context():
        product = make_product()
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


def test_product_factory_records_stock_in_the_ledger(app: Flask) -> None:
    with app.app_context():
        product = make_product(stock=7)

        movements = db.session.query(StockMovement).filter_by(product_id=product.id).all()

        assert product.stock_on_hand == 7
        assert [(m.quantity, m.reason) for m in movements] == [(7, "initial")]
