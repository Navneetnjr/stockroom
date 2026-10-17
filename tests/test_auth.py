from datetime import timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token

from app.errors import PROBLEM_CONTENT_TYPE
from app.services import accounts
from tests.helpers import PASSWORD, auth_header, login, register_shop

SIGNUP = {"shop_name": "Shoe Shop", "email": "Owner@Shoe.test", "password": PASSWORD}


def test_register_creates_shop_and_admin(client: FlaskClient) -> None:
    response = client.post("/auth/register", json=SIGNUP)

    assert response.status_code == 201
    body = response.get_json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "owner@shoe.test"  # stored in lower case
    assert body["user"]["role"] == "admin"
    assert body["tenant"]["name"] == "Shoe Shop"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_with_taken_email_returns_409(client: FlaskClient) -> None:
    register_shop(client)

    response = client.post("/auth/register", json={**SIGNUP, "shop_name": "Another Shop"})

    assert response.status_code == 409
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert "already registered" in response.get_json()["detail"]


def test_simultaneous_signups_with_same_email_return_409(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_shop(client)
    # Skip the friendly pre-check, as if both sign-ups arrived at the same moment:
    # the database's unique rule must still stop the duplicate
    monkeypatch.setattr(accounts, "_email_taken", lambda email: False)

    response = client.post("/auth/register", json={**SIGNUP, "shop_name": "Another Shop"})

    assert response.status_code == 409


def test_register_with_bad_input_returns_422_with_field_errors(client: FlaskClient) -> None:
    response = client.post(
        "/auth/register", json={"shop_name": "", "email": "not-an-email", "password": "short"}
    )

    assert response.status_code == 422
    assert response.content_type == PROBLEM_CONTENT_TYPE
    body = response.get_json()
    assert body["title"] == "Unprocessable Entity"
    assert set(body["errors"]["json"]) == {"shop_name", "email", "password"}


def test_login_returns_token_that_works_on_me(client: FlaskClient) -> None:
    register_shop(client)

    token = login(client, "owner@shoe.test")
    response = client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == 200
    assert response.get_json()["email"] == "owner@shoe.test"
    assert response.get_json()["role"] == "admin"


@pytest.mark.parametrize(
    ("email", "password"),
    [("owner@shoe.test", "wrong-password"), ("nobody@shoe.test", PASSWORD)],
)
def test_login_with_wrong_credentials_returns_401(
    client: FlaskClient, email: str, password: str
) -> None:
    register_shop(client)

    response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.get_json()["detail"] == "Invalid email or password."


def test_me_without_token_returns_401(client: FlaskClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_with_garbage_token_returns_401(client: FlaskClient) -> None:
    response = client.get("/auth/me", headers=auth_header("not-a-real-token"))

    assert response.status_code == 401
    assert "not valid" in response.get_json()["detail"]


def test_me_with_expired_token_returns_401(app: Flask, client: FlaskClient) -> None:
    register_shop(client)
    with app.app_context():
        token = create_access_token(
            identity="1",
            additional_claims={"tenant_id": 1, "role": "admin"},
            expires_delta=timedelta(seconds=-1),
        )

    response = client.get("/auth/me", headers=auth_header(token))

    assert response.status_code == 401
    assert "expired" in response.get_json()["detail"]
