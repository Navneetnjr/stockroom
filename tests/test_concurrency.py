"""Proves that parallel orders for a scarce product never oversell it."""

import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from flask.testing import FlaskClient

from tests.helpers import auth_header, create_product, place_order, register_shop, stock_of

PARALLEL_REQUESTS = 10
STOCK = 5


def test_parallel_orders_never_oversell(app: Flask, client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin, initial_stock=STOCK)
    # Every thread waits here until all are ready, so the requests really overlap
    start_line = threading.Barrier(PARALLEL_REQUESTS)

    def buy_one(_: int) -> int:
        own_client = app.test_client()  # each thread has its own client and DB connection
        start_line.wait(timeout=30)
        return place_order(own_client, admin, (product["id"], 1)).status_code

    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        statuses = list(pool.map(buy_one, range(PARALLEL_REQUESTS)))

    # Exactly as many orders succeed as there was stock; the rest are told "insufficient stock"
    assert sorted(statuses) == [201] * STOCK + [409] * (PARALLEL_REQUESTS - STOCK)
    assert stock_of(client, admin, product["id"]) == 0
    history = client.get(
        f"/products/{product['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert sum(movement["quantity"] for movement in history) == 0  # ledger agrees with stock
    orders = client.get("/orders", headers=auth_header(admin)).get_json()["items"]
    assert len(orders) == STOCK
