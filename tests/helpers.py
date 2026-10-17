"""Small helpers shared by the tests (they assume a client with a clean database)."""

import os
from typing import Any

from flask.testing import FlaskClient

PASSWORD = "password123"


def settings_for_tests() -> dict[str, Any]:
    """App settings every test app uses: the test database and a fixed JWT secret."""
    return {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": os.environ["TEST_DATABASE_URL"],
        "JWT_SECRET_KEY": "test-only-secret-key-that-is-long-enough-0123456789",
    }


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
