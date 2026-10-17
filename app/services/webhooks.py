"""Webhooks: tell a tenant's own system when one of its orders changes status.

1. In the same transaction as the order change, the event is saved as a WebhookDelivery.
2. After the commit, a background task (send_webhook) POSTs it to the tenant's URL.
3. The body is signed with HMAC-SHA256 using the tenant's secret, so the receiver can check
   it really came from Stockroom and was not changed on the way.
4. A failed attempt is retried after 2 s, 4 s, 8 s, ...; after WEBHOOK_MAX_ATTEMPTS the event
   is copied to the webhook_dead_letters table and no longer retried.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import UTC, datetime

import requests
from celery import shared_task
from flask import current_app
from kombu.exceptions import OperationalError
from sqlalchemy import select

from app.extensions import db
from app.models import DeliveryStatus, Order, Tenant, WebhookDeadLetter, WebhookDelivery
from app.observability import bind_request_id, current_request_id
from app.schemas.orders import OrderSchema

ORDER_STATUS_CHANGED = "order.status_changed"
_log = logging.getLogger("stockroom.webhooks")


# --- Settings ---------------------------------------------------------------------------


def get_tenant(tenant_id: int) -> Tenant:
    return db.session.get_one(Tenant, tenant_id)


def configure(tenant_id: int, url: str, secret: str | None) -> Tenant:
    """Set the tenant's webhook URL and signing secret (a random one if none is given)."""
    tenant = get_tenant(tenant_id)
    tenant.webhook_url = url
    tenant.webhook_secret = secret or secrets.token_hex(32)
    db.session.commit()
    return tenant


def list_deliveries(tenant_id: int, limit: int = 50) -> list[WebhookDelivery]:
    query = (
        select(WebhookDelivery)
        .where(WebhookDelivery.tenant_id == tenant_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
    )
    return list(db.session.scalars(query))


# --- Pure rules -------------------------------------------------------------------------


def sign(secret: str, timestamp: str, body: str) -> str:
    """Signature of "<timestamp>.<body>". The timestamp lets receivers reject old replays."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def backoff_seconds(attempt: int) -> float:
    """How long to wait after failed attempt number `attempt`: 2 s, 4 s, 8 s, ... (max 1 hour)."""
    base = float(current_app.config["WEBHOOK_BACKOFF_SECONDS"])
    return min(base * 2.0 ** (attempt - 1), 3600.0)


# --- Creating and sending events --------------------------------------------------------


def queue_order_event(order: Order, previous_status: str) -> WebhookDelivery | None:
    """Save an order status change for sending, if the tenant has a webhook. Caller commits."""
    tenant = get_tenant(order.tenant_id)
    if not tenant.webhook_url:
        return None

    event_id = str(uuid.uuid4())
    delivery = WebhookDelivery(
        tenant_id=order.tenant_id,
        event_id=event_id,
        event_type=ORDER_STATUS_CHANGED,
        target_url=tenant.webhook_url,
        payload={
            "id": event_id,
            "type": ORDER_STATUS_CHANGED,
            "created_at": datetime.now(UTC).isoformat(),
            "tenant_id": order.tenant_id,
            "data": {
                "previous_status": previous_status,
                "status": order.status,
                "order": OrderSchema().dump(order),
            },
        },
    )
    db.session.add(delivery)
    return delivery


def queue_delivery(delivery_id: int) -> None:
    """Hand a saved delivery to the worker for its first attempt."""
    _schedule_attempt(delivery_id, current_request_id())


def _schedule_attempt(delivery_id: int, request_id: str | None, countdown: float = 0) -> None:
    """Queue an attempt to run after `countdown` seconds (0 = as soon as possible).

    If the queue is down, the delivery simply stays pending in the table.
    """
    try:
        send_webhook.apply_async((delivery_id,), {"request_id": request_id}, countdown=countdown)
    except OperationalError:
        _log.error(
            "could not queue webhook delivery %s; it stays pending", delivery_id, exc_info=True
        )


def attempt_delivery(delivery_id: int) -> float | None:
    """Make one attempt to send a webhook.

    Returns how many seconds to wait before the next attempt, or None when there is nothing
    more to do (delivered, given up, or already handled by an earlier run).
    """
    delivery = db.session.get(WebhookDelivery, delivery_id, with_for_update=True)
    if delivery is None or delivery.status != DeliveryStatus.PENDING:
        return None  # running the task again for a finished delivery changes nothing

    tenant = get_tenant(delivery.tenant_id)
    delivery.attempts += 1
    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Stockroom-Event": delivery.event_type,
        "X-Stockroom-Event-Id": delivery.event_id,
        "X-Stockroom-Timestamp": timestamp,
        "X-Stockroom-Signature": sign(tenant.webhook_secret or "", timestamp, body),
        "X-Request-ID": current_request_id() or "",
    }

    try:
        response = requests.post(
            delivery.target_url,
            data=body,
            headers=headers,
            timeout=current_app.config["WEBHOOK_TIMEOUT_SECONDS"],
            allow_redirects=False,
        )
        error = None if 200 <= response.status_code < 300 else f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"

    if error is None:
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = datetime.now(UTC)
        delivery.last_error = None
        db.session.commit()
        _log.info("webhook delivered", extra={"event_id": delivery.event_id})
        return None

    delivery.last_error = error[:1000]
    if delivery.attempts >= current_app.config["WEBHOOK_MAX_ATTEMPTS"]:
        delivery.status = DeliveryStatus.DEAD
        db.session.add(
            WebhookDeadLetter(
                tenant_id=delivery.tenant_id,
                delivery_id=delivery.id,
                event_id=delivery.event_id,
                event_type=delivery.event_type,
                payload=delivery.payload,
                target_url=delivery.target_url,
                attempts=delivery.attempts,
                last_error=delivery.last_error,
            )
        )
        db.session.commit()
        _log.warning(
            "webhook moved to the dead-letter table",
            extra={"event_id": delivery.event_id, "attempts": delivery.attempts, "error": error},
        )
        return None

    db.session.commit()
    return backoff_seconds(delivery.attempts)


@shared_task(name="stockroom.send_webhook")
def send_webhook(delivery_id: int, request_id: str | None = None) -> None:
    """Background task: one attempt; if it failed, schedule the next one after a wait."""
    bind_request_id(request_id)
    retry_in = attempt_delivery(delivery_id)
    if retry_in is not None:
        _schedule_attempt(delivery_id, request_id, countdown=retry_in)
