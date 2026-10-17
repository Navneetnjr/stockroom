"""Product cache tests, using fakeredis: an in-memory stand-in for a real Redis server."""

from collections.abc import Callable

import fakeredis
import pytest
import redis
from flask.testing import FlaskClient

from app import create_app
from tests.helpers import (
    auth_header,
    create_product,
    place_order,
    register_shop,
    set_status,
    settings_for_tests,
)

ClientFactory = Callable[[fakeredis.FakeRedis], FlaskClient]


@pytest.fixture
def client_with_redis(monkeypatch: pytest.MonkeyPatch) -> ClientFactory:
    """Build a client whose app talks to the given fake Redis."""

    def build(fake: fakeredis.FakeRedis) -> FlaskClient:
        monkeypatch.setattr(redis.Redis, "from_url", lambda url, **options: fake)
        app = create_app(settings_for_tests() | {"REDIS_URL": "redis://fake:6379/0"})
        return app.test_client()

    return build


@pytest.fixture
def cached_client(client_with_redis: ClientFactory) -> FlaskClient:
    return client_with_redis(fakeredis.FakeRedis(decode_responses=True))


@pytest.fixture
def broken_redis_client(client_with_redis: ClientFactory) -> FlaskClient:
    server = fakeredis.FakeServer()
    server.connected = False  # every command fails, like a Redis that is down
    return client_with_redis(fakeredis.FakeRedis(server=server, decode_responses=True))


def test_second_read_is_served_from_the_cache(cached_client: FlaskClient) -> None:
    admin = register_shop(cached_client)
    product = create_product(cached_client, admin)

    for url in ("/products", f"/products/{product['id']}"):
        first = cached_client.get(url, headers=auth_header(admin))
        second = cached_client.get(url, headers=auth_header(admin))

        assert first.headers["X-Cache"] == "MISS"
        assert second.headers["X-Cache"] == "HIT"
        assert second.get_json() == first.get_json()  # exactly the same answer


def test_every_change_clears_the_cache(cached_client: FlaskClient) -> None:
    admin = register_shop(cached_client)
    product = create_product(cached_client, admin, initial_stock=10)
    url = f"/products/{product['id']}"

    def read() -> tuple[str, dict[str, object]]:
        response = cached_client.get(url, headers=auth_header(admin))
        return response.headers["X-Cache"], response.get_json()

    read()
    assert read()[0] == "HIT"

    cached_client.patch(url, json={"name": "Blue Shoe"}, headers=auth_header(admin))
    assert read() == ("MISS", read()[1]) and read()[1]["name"] == "Blue Shoe"

    cached_client.post(f"{url}/stock-movements", json={"quantity": 5}, headers=auth_header(admin))
    assert read()[1]["stock_on_hand"] == 15

    order = place_order(cached_client, admin, (product["id"], 2)).get_json()
    assert read()[1]["stock_on_hand"] == 13

    set_status(cached_client, admin, order["id"], "cancelled")
    assert read()[1]["stock_on_hand"] == 15

    cached_client.delete(url, headers=auth_header(admin))
    assert cached_client.get(url, headers=auth_header(admin)).status_code == 404
    assert cached_client.get("/products", headers=auth_header(admin)).get_json() == []


def test_each_shop_has_its_own_cache(cached_client: FlaskClient) -> None:
    shoe_shop = register_shop(cached_client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(cached_client, "Bakery", "owner@bakery.test")
    create_product(cached_client, shoe_shop)
    cached_client.get("/products", headers=auth_header(shoe_shop))  # fills the shoe shop's cache

    response = cached_client.get("/products", headers=auth_header(bakery))

    assert response.headers["X-Cache"] == "MISS"
    assert response.get_json() == []


def test_broken_redis_falls_back_to_the_database(broken_redis_client: FlaskClient) -> None:
    admin = register_shop(broken_redis_client)
    create_product(broken_redis_client, admin)

    response = broken_redis_client.get("/products", headers=auth_header(admin))

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert [p["sku"] for p in response.get_json()] == ["RED-SHOE"]


def test_failed_cache_save_still_answers(
    client_with_redis: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    client = client_with_redis(fake)
    admin = register_shop(client)
    create_product(client, admin)

    def failing_set(*args: object, **kwargs: object) -> None:
        raise redis.ConnectionError("Redis went away")

    monkeypatch.setattr(fake, "set", failing_set)  # reading works, saving fails

    first = client.get("/products", headers=auth_header(admin))
    second = client.get("/products", headers=auth_header(admin))

    assert first.status_code == second.status_code == 200
    assert second.headers["X-Cache"] == "MISS"  # nothing was saved, so no hit


def test_readyz_reports_redis_up(cached_client: FlaskClient) -> None:
    response = cached_client.get("/readyz")

    assert response.status_code == 200
    assert response.get_json()["redis"] == "up"


def test_readyz_fails_when_redis_is_down(broken_redis_client: FlaskClient) -> None:
    response = broken_redis_client.get("/readyz")

    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable", "database": "up", "redis": "down"}
