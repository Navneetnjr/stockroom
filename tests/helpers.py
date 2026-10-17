"""Small helpers shared by the tests (they assume a client with a clean database)."""

import os
from typing import Any

from alembic.config import Config as AlembicConfig
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

PASSWORD = "password123"


def settings_for_tests() -> dict[str, Any]:
    """App settings every test app uses: the test database and a fixed JWT secret."""
    return {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": os.environ["TEST_DATABASE_URL"],
        "JWT_SECRET_KEY": "test-only-secret-key-that-is-long-enough-0123456789",
        # Light password hashing: tests need speed, not protection against attackers
        "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000",
        # No real Redis in tests: cache tests plug in a fake one, rate limits count in memory
        "REDIS_URL": None,
        "RATELIMIT_STORAGE_URI": "memory://",
        # Background jobs run straight away inside the test ("eager"), no worker needed
        "CELERY_TASK_ALWAYS_EAGER": True,
        "CELERY_BROKER_URL": "memory://",
    }


def alembic_config() -> AlembicConfig:
    """Alembic settings pointed at the test database."""
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"].replace("%", "%%"))
    return config


def register_shop(
    client: FlaskClient, shop_name: str = "Shoe Shop", email: str = "owner@shoe.test"
) -> str:
    """Register a shop and return its admin's login token."""
    response = client.post(
        "/auth/register", json={"shop_name": shop_name, "email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.get_json()
    token: str = response.get_json()["access_token"]
    return token


def login(client: FlaskClient, email: str, password: str = PASSWORD) -> str:
    """Log in and return the token."""
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.get_json()
    token: str = response.get_json()["access_token"]
    return token


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def add_staff(client: FlaskClient, admin_token: str, email: str = "cashier@shoe.test") -> str:
    """Add a staff user with the admin's token and return the staff user's token."""
    response = client.post(
        "/users", json={"email": email, "password": PASSWORD}, headers=auth_header(admin_token)
    )
    assert response.status_code == 201, response.get_json()
    return login(client, email)


def create_product(client: FlaskClient, admin_token: str, **fields: Any) -> dict[str, Any]:
    """Create a product (defaults: RED-SHOE, 499.00, 10 in stock) and return its JSON."""
    body = {"sku": "RED-SHOE", "name": "Red Shoe", "price": "499.00", "initial_stock": 10}
    response = client.post("/products", json=body | fields, headers=auth_header(admin_token))
    assert response.status_code == 201, response.get_json()
    product: dict[str, Any] = response.get_json()
    return product


def place_order(
    client: FlaskClient, token: str, *lines: tuple[int, int], key: str | None = None
) -> TestResponse:
    """POST /orders with (product_id, quantity) lines, optionally with an Idempotency-Key."""
    headers = auth_header(token)
    if key:
        headers["Idempotency-Key"] = key
    body = {"lines": [{"product_id": pid, "quantity": qty} for pid, qty in lines]}
    return client.post("/orders", json=body, headers=headers)


def set_status(client: FlaskClient, token: str, order_id: int, status: str) -> TestResponse:
    return client.post(
        f"/orders/{order_id}/transitions", json={"status": status}, headers=auth_header(token)
    )


def stock_of(client: FlaskClient, token: str, product_id: int) -> int:
    response = client.get(f"/products/{product_id}", headers=auth_header(token))
    stock: int = response.get_json()["stock_on_hand"]
    return stock
