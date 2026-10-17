"""Webhook tests. Instead of a real network call, requests.post is replaced by a fake receiver
that records what it got and answers with the status codes we choose."""

import hashlib
import hmac
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from flask import Flask
from flask.testing import FlaskClient
from kombu.exceptions import OperationalError
from sqlalchemy import select

from app.extensions import db
from app.models import WebhookDeadLetter
from app.services import webhooks
from tests.helpers import add_staff, auth_header, create_product, place_order, register_shop

SECRET = "receiver-shared-secret-123"


class FakeReceiver:
    """Stands in for the shop's server: records each call and replies with `statuses`."""

    def __init__(self, statuses: list[int | Exception]) -> None:
        self.statuses = statuses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, data: str, headers: dict[str, str], **kwargs: Any) -> Any:
        self.calls.append({"url": url, "body": data, "headers": headers})
        outcome = self.statuses[min(len(self.calls), len(self.statuses)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(status_code=outcome)


ReceiverFactory = Callable[[list[int | Exception]], FakeReceiver]


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> ReceiverFactory:
    def install(statuses: list[int | Exception]) -> FakeReceiver:
        fake = FakeReceiver(statuses)
        monkeypatch.setattr(requests, "post", fake)
        return fake

    return install


def shop_with_order(
    client: FlaskClient, webhook_url: str | None = "https://shop.test/hook"
) -> tuple[str, int]:
    """A shop (optionally with a webhook) and one draft order. Returns (admin token, order id)."""
    admin = register_shop(client)
    if webhook_url:
        response = client.put(
            "/webhooks/config",
            json={"url": webhook_url, "secret": SECRET},
            headers=auth_header(admin),
        )
        assert response.status_code == 200
    product = create_product(client, admin)
    order_id: int = place_order(client, admin, (product["id"], 1)).get_json()["id"]
    return admin, order_id


def confirm(client: FlaskClient, token: str, order_id: int, request_id: str = "req-abc") -> None:
    response = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "confirmed"},
        headers=auth_header(token) | {"X-Request-ID": request_id},
    )
    assert response.status_code == 200


def deliveries(client: FlaskClient, token: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get(
        "/webhooks/deliveries", headers=auth_header(token)
    ).get_json()
    return result


# --- Settings ---------------------------------------------------------------------------


def test_admin_sets_webhook_url_and_gets_a_secret(client: FlaskClient) -> None:
    admin = register_shop(client)

    before = client.get("/webhooks/config", headers=auth_header(admin)).get_json()
    saved = client.put(
        "/webhooks/config", json={"url": "https://shop.test/hook"}, headers=auth_header(admin)
    ).get_json()
    after = client.get("/webhooks/config", headers=auth_header(admin)).get_json()

    assert before == {"url": None, "configured": False}
    assert len(saved["secret"]) == 64  # generated, shown once
    assert after == {"url": "https://shop.test/hook", "configured": True}  # no secret here


def test_webhook_settings_are_admin_only_and_validated(client: FlaskClient) -> None:
    admin = register_shop(client)
    staff = add_staff(client, admin)

    as_staff = client.get("/webhooks/config", headers=auth_header(staff))
    bad_url = client.put("/webhooks/config", json={"url": "not a url"}, headers=auth_header(admin))

    assert as_staff.status_code == 403
    assert bad_url.status_code == 422


# --- Sending ----------------------------------------------------------------------------


def test_status_change_sends_a_signed_webhook(
    client: FlaskClient, receiver: ReceiverFactory
) -> None:
    fake = receiver([200])
    admin, order_id = shop_with_order(client)

    confirm(client, admin, order_id, request_id="req-abc")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    headers, body = call["headers"], call["body"]
    assert call["url"] == "https://shop.test/hook"
    # The receiver can check the signature with the shared secret
    expected = hmac.new(
        SECRET.encode(), f"{headers['X-Stockroom-Timestamp']}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert headers["X-Stockroom-Signature"] == f"sha256={expected}"
    event = json.loads(body)
    assert event["type"] == headers["X-Stockroom-Event"] == "order.status_changed"
    assert event["id"] == headers["X-Stockroom-Event-Id"]
    assert (event["data"]["previous_status"], event["data"]["status"]) == ("draft", "confirmed")
    assert event["data"]["order"]["id"] == order_id
    assert headers["X-Request-ID"] == "req-abc"  # the request id travels to the webhook
    assert (
        deliveries(client, admin)[0] | {"status": "delivered", "attempts": 1}
        == deliveries(client, admin)[0]
    )


def test_no_webhook_configured_means_nothing_is_sent(
    client: FlaskClient, receiver: ReceiverFactory
) -> None:
    fake = receiver([200])
    admin, order_id = shop_with_order(client, webhook_url=None)

    confirm(client, admin, order_id)

    assert fake.calls == []
    assert deliveries(client, admin) == []


def test_failed_sends_are_retried_until_they_succeed(
    client: FlaskClient, receiver: ReceiverFactory
) -> None:
    fake = receiver([500, requests.ConnectionError("connection refused"), 200])
    admin, order_id = shop_with_order(client)

    confirm(client, admin, order_id)

    assert len(fake.calls) == 3
    delivery = deliveries(client, admin)[0]
    assert (delivery["status"], delivery["attempts"], delivery["last_error"]) == (
        "delivered",
        3,
        None,
    )
    # Every retry sends the same event, so the receiver can ignore duplicates by its id
    assert len({call["headers"]["X-Stockroom-Event-Id"] for call in fake.calls}) == 1


def test_after_the_last_attempt_it_moves_to_the_dead_letter_table(
    app: Flask, client: FlaskClient, receiver: ReceiverFactory
) -> None:
    fake = receiver([500])
    admin, order_id = shop_with_order(client)

    confirm(client, admin, order_id)

    assert len(fake.calls) == 5  # WEBHOOK_MAX_ATTEMPTS
    delivery = deliveries(client, admin)[0]
    assert (delivery["status"], delivery["attempts"], delivery["last_error"]) == (
        "dead",
        5,
        "HTTP 500",
    )
    with app.app_context():
        dead = db.session.scalars(select(WebhookDeadLetter)).all()
    assert [(d.event_id, d.attempts) for d in dead] == [(delivery["event_id"], 5)]


def test_sending_a_finished_delivery_again_does_nothing(
    app: Flask, client: FlaskClient, receiver: ReceiverFactory
) -> None:
    fake = receiver([200])
    admin, order_id = shop_with_order(client)
    confirm(client, admin, order_id)

    with app.app_context():
        result = webhooks.attempt_delivery(deliveries(client, admin)[0]["id"])

    assert result is None
    assert len(fake.calls) == 1  # no second POST


def test_queue_down_keeps_the_delivery_pending(
    client: FlaskClient, receiver: ReceiverFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = receiver([200])
    admin, order_id = shop_with_order(client)

    def broken_delay(*args: object, **kwargs: object) -> None:
        raise OperationalError("Redis is down")

    monkeypatch.setattr(webhooks.send_webhook, "apply_async", broken_delay)

    confirm(client, admin, order_id)  # the status change itself still succeeds

    assert fake.calls == []
    assert deliveries(client, admin)[0]["status"] == "pending"


def test_backoff_doubles_each_time_and_is_capped(app: Flask) -> None:
    with app.app_context():
        waits = [webhooks.backoff_seconds(attempt) for attempt in (1, 2, 3, 4, 20)]

    assert waits == [2.0, 4.0, 8.0, 16.0, 3600.0]
