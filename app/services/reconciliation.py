"""Stock reconciliation: a scheduled check that every product's stock_on_hand still equals
the sum of its stock ledger. A mismatch ("drift") means something changed stock without
writing to the ledger, so it is logged as an ERROR, which log monitoring can alert on.

The job only reads, so running it twice (or at the same time) is harmless.
"""

import logging
from typing import Any

from celery import shared_task
from sqlalchemy import func, select

from app.extensions import db
from app.models import Product, StockMovement

_log = logging.getLogger("stockroom.reconciliation")


def find_stock_drift() -> list[dict[str, Any]]:
    """Products (of every tenant) whose stock_on_hand differs from their ledger total."""
    ledger_total = func.coalesce(func.sum(StockMovement.quantity), 0)
    query = (
        select(
            Product.id.label("product_id"),
            Product.tenant_id,
            Product.stock_on_hand,
            ledger_total.label("ledger_total"),
        )
        .outerjoin(StockMovement, StockMovement.product_id == Product.id)
        .group_by(Product.id)
        .having(Product.stock_on_hand != ledger_total)
        .order_by(Product.id)
    )
    return [dict(row._mapping) for row in db.session.execute(query)]


@shared_task(name="stockroom.reconcile_stock")
def reconcile_stock() -> int:
    """Scheduled task (Celery beat): log every drift found; returns how many products drifted."""
    drift = find_stock_drift()
    for item in drift:
        _log.error("stock drift detected", extra=item)
    _log.info("stock reconciliation finished", extra={"products_with_drift": len(drift)})
    return len(drift)
