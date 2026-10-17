import pytest
from flask import Flask

from app import create_app
from app.errors import PROBLEM_CONTENT_TYPE
from tests.helpers import auth_header, register_shop, settings_for_tests


@pytest.fixture
def strict_app() -> Flask:
    """An app with tiny limits, so tests can hit them quickly."""
    return create_app(
        settings_for_tests()
        | {"RATE_LIMIT_DEFAULT": "3 per minute", "RATE_LIMIT_AUTH": "2 per minute"}
    )


def test_each_shop_has_its_own_counter_per_endpoint(strict_app: Flask) -> None:
    client = strict_app.test_client()
    shoe_shop = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")

    responses = [client.get("/products", headers=auth_header(shoe_shop)) for _ in range(4)]

    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    blocked = responses[-1]
    assert blocked.content_type == PROBLEM_CONTENT_TYPE
    assert blocked.get_json()["title"] == "Too Many Requests"
    assert int(blocked.headers["Retry-After"]) > 0
    # Another shop, and another endpoint, still have their own room
    assert client.get("/products", headers=auth_header(bakery)).status_code == 200
    assert client.get("/orders", headers=auth_header(shoe_shop)).status_code == 200


def test_responses_say_how_many_requests_are_left(strict_app: Flask) -> None:
    client = strict_app.test_client()
    token = register_shop(client)

    response = client.get("/products", headers=auth_header(token))

    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "2"


def test_login_attempts_are_limited_per_ip_address(strict_app: Flask) -> None:
    client = strict_app.test_client()
    wrong = {"email": "someone@shop.test", "password": "guessing123"}

    statuses = [client.post("/auth/login", json=wrong).status_code for _ in range(3)]

    assert statuses == [401, 401, 429]


def test_health_checks_and_docs_are_never_limited(strict_app: Flask) -> None:
    client = strict_app.test_client()

    statuses = {client.get(url).status_code for url in ["/healthz", "/openapi.json"] * 5}

    assert statuses == {200}
