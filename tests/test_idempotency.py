from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select, update

from app import idempotency
from app.extensions import db
from app.models import IdempotencyKey, Tenant
from tests.helpers import auth_header, create_product, place_order, register_shop, stock_of


def test_repeated_request_with_same_key_creates_only_one_order(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)

    first = place_order(client, admin, (shoe["id"], 2), key="order-abc-1")
    second = place_order(client, admin, (shoe["id"], 2), key="order-abc-1")

    assert first.status_code == second.status_code == 201
    assert second.get_json() == first.get_json()  # the same order, replayed
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert stock_of(client, admin, shoe["id"]) == 8  # stock taken once, not twice
    assert len(client.get("/orders", headers=auth_header(admin)).get_json()["items"]) == 1


def test_different_keys_are_different_orders(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)

    place_order(client, admin, (shoe["id"], 1), key="key-1")
    place_order(client, admin, (shoe["id"], 1), key="key-2")

    assert stock_of(client, admin, shoe["id"]) == 8


def test_same_key_with_a_different_body_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)
    place_order(client, admin, (shoe["id"], 1), key="key-1")

    response = place_order(client, admin, (shoe["id"], 5), key="key-1")

    assert response.status_code == 422
    assert response.get_json()["type"] == "/problems/idempotency-key-reused"


def test_failed_request_releases_the_key_for_a_retry(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=1)
    url = f"/products/{shoe['id']}/stock-movements"

    failed = place_order(client, admin, (shoe["id"], 3), key="retry-me")  # only 1 in stock
    client.post(url, json={"quantity": 5}, headers=auth_header(admin))  # restock
    retried = place_order(client, admin, (shoe["id"], 3), key="retry-me")

    assert failed.status_code == 409
    assert retried.status_code == 201


def test_key_still_in_progress_returns_409(
    app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)
    monkeypatch.setattr(idempotency, "_fingerprint", lambda: "same-request")
    # Pretend the same request started a moment ago and hasn't finished yet
    with app.app_context():
        tenant_id = db.session.scalar(select(Tenant.id))
        db.session.add(IdempotencyKey(tenant_id=tenant_id, key="busy", request_hash="same-request"))
        db.session.commit()

    response = place_order(client, admin, (shoe["id"], 1), key="busy")

    assert response.status_code == 409
    assert "still being processed" in response.get_json()["detail"]


def test_two_identical_requests_at_the_same_moment_create_one_order(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)
    place_order(client, admin, (shoe["id"], 1), key="race")
    # Make the second request miss the saved key, as if both looked at the same instant:
    # the database's unique rule must still stop it
    monkeypatch.setattr(idempotency, "_find", lambda tenant_id, key: None)

    second = place_order(client, admin, (shoe["id"], 1), key="race")

    assert second.status_code == 409
    assert stock_of(client, admin, shoe["id"]) == 9


def test_expired_key_is_treated_as_new(app: Flask, client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)
    place_order(client, admin, (shoe["id"], 1), key="old-key")
    with app.app_context():  # age the saved key past its 24-hour lifetime
        db.session.execute(
            update(IdempotencyKey).values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
        db.session.commit()

    again = place_order(client, admin, (shoe["id"], 1), key="old-key")

    assert again.status_code == 201
    assert "Idempotent-Replayed" not in again.headers
    assert stock_of(client, admin, shoe["id"]) == 8


def test_keys_are_separate_per_shop(client: FlaskClient) -> None:
    shoe_shop = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    shoe = create_product(client, shoe_shop)
    bread = create_product(client, bakery, sku="BREAD")

    first = place_order(client, shoe_shop, (shoe["id"], 1), key="same-key")
    second = place_order(client, bakery, (bread["id"], 1), key="same-key")

    assert first.status_code == second.status_code == 201
    assert first.get_json()["id"] != second.get_json()["id"]


def test_product_creation_is_idempotent_too(client: FlaskClient) -> None:
    admin = register_shop(client)
    body = {"sku": "HAT", "name": "Hat", "price": "99.00"}
    headers = auth_header(admin) | {"Idempotency-Key": "create-hat"}

    first = client.post("/products", json=body, headers=headers)
    second = client.post("/products", json=body, headers=headers)

    assert first.status_code == second.status_code == 201  # not 409 "SKU already exists"
    assert second.get_json()["id"] == first.get_json()["id"]


def test_overlong_key_returns_400(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)

    response = place_order(client, admin, (shoe["id"], 1), key="k" * 256)

    assert response.status_code == 400
