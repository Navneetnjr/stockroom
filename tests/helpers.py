"""Small helpers shared by the tests."""

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
