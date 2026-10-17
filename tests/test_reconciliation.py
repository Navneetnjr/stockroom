import logging

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app.extensions import db
from app.services.reconciliation import find_stock_drift, reconcile_stock
from tests.factories import make_product
from tests.helpers import create_product, place_order, register_shop


def test_no_drift_when_stock_matches_the_ledger(app: Flask, client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin, initial_stock=10)
    place_order(client, admin, (product["id"], 3))  # stock changed through the real API
    with app.app_context():
        make_product(stock=5)
        make_product()  # no ledger lines at all

        assert find_stock_drift() == []


def test_drift_is_found_and_logged_as_an_error(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    with app.app_context():
        product_id = make_product(stock=10).id
        # Change stock behind the ledger's back, as a buggy script might
        db.session.execute(text("UPDATE products SET stock_on_hand = 99"))
        db.session.commit()

        drifted = reconcile_stock.delay().get()  # the scheduled task, run straight away here

    assert drifted == 1
    record = next(r for r in caplog.records if r.getMessage() == "stock drift detected")
    assert record.levelno == logging.ERROR
    assert (record.__dict__["product_id"], record.__dict__["stock_on_hand"]) == (product_id, 99)
    assert record.__dict__["ledger_total"] == 10


def test_reconciliation_is_scheduled(app: Flask) -> None:
    schedule = app.extensions["celery"].conf.beat_schedule

    assert schedule["reconcile-stock"]["task"] == "stockroom.reconcile_stock"
    assert schedule["reconcile-stock"]["schedule"] == 900
