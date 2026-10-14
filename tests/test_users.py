from flask.testing import FlaskClient

from tests.helpers import PASSWORD, auth_header, login, register_shop

CASHIER = {"email": "cashier@shoe.test", "password": PASSWORD}


def test_admin_can_add_staff_who_can_then_log_in(client: FlaskClient) -> None:
    admin_token = register_shop(client)

    response = client.post("/users", json=CASHIER, headers=auth_header(admin_token))

    assert response.status_code == 201
    assert response.get_json()["role"] == "staff"
    assert login(client, "cashier@shoe.test")


def test_staff_cannot_add_or_list_users(client: FlaskClient) -> None:
    admin_token = register_shop(client)
    client.post("/users", json=CASHIER, headers=auth_header(admin_token))
    staff_token = login(client, "cashier@shoe.test")

    add = client.post(
        "/users", json={**CASHIER, "email": "x@shoe.test"}, headers=auth_header(staff_token)
    )
    listing = client.get("/users", headers=auth_header(staff_token))

    assert add.status_code == 403
    assert listing.status_code == 403
    assert "admin" in listing.get_json()["detail"]


def test_users_list_only_shows_your_own_shop(client: FlaskClient) -> None:
    shoe_token = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery_token = register_shop(client, "Bakery", "owner@bakery.test")
    client.post("/users", json=CASHIER, headers=auth_header(shoe_token))

    response = client.get("/users", headers=auth_header(bakery_token))

    assert response.status_code == 200
    assert [user["email"] for user in response.get_json()] == ["owner@bakery.test"]


def test_adding_user_with_taken_email_returns_409(client: FlaskClient) -> None:
    admin_token = register_shop(client)

    response = client.post(
        "/users", json={**CASHIER, "email": "owner@shoe.test"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 409


def test_adding_user_with_unknown_role_returns_422(client: FlaskClient) -> None:
    admin_token = register_shop(client)

    response = client.post(
        "/users", json={**CASHIER, "role": "superuser"}, headers=auth_header(admin_token)
    )

    assert response.status_code == 422
    assert "role" in response.get_json()["errors"]["json"]
