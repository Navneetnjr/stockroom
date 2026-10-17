from typing import Any

from flask_smorest import Blueprint

from app.auth import REQUIRES_LOGIN, auth_required, current_tenant_id
from app.errors import ProblemSchema
from app.models import Tenant, UserRole, WebhookDelivery
from app.schemas.webhooks import (
    WebhookConfigInSchema,
    WebhookConfigSchema,
    WebhookConfigWithSecretSchema,
    WebhookDeliverySchema,
)
from app.services import webhooks

blp = Blueprint("webhooks", __name__, url_prefix="/webhooks", description="Order webhooks (admin)")


def _config(tenant: Tenant) -> dict[str, Any]:
    return {"url": tenant.webhook_url, "configured": bool(tenant.webhook_url)}


@blp.route("/config", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.response(200, WebhookConfigSchema)
@blp.alt_response(403, schema=ProblemSchema, description="Only admins can do this")
def get_config() -> dict[str, Any]:
    """Get the webhook URL

    The URL your shop's order events are sent to. **Admin only.**
    """
    return _config(webhooks.get_tenant(current_tenant_id()))


@blp.route("/config", methods=["PUT"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.arguments(WebhookConfigInSchema)
@blp.response(200, WebhookConfigWithSecretSchema)
@blp.alt_response(403, schema=ProblemSchema, description="Only admins can do this")
def set_config(data: dict[str, str]) -> dict[str, Any]:
    """Set the webhook URL

    Order status changes are POSTed to this URL as signed JSON. The response contains the
    signing secret: check each webhook with `X-Stockroom-Signature` =
    `sha256=` + HMAC-SHA256(secret, `<X-Stockroom-Timestamp>.<raw body>`). **Admin only.**
    """
    tenant = webhooks.configure(current_tenant_id(), data["url"], data.get("secret"))
    return _config(tenant) | {"secret": tenant.webhook_secret}


@blp.route("/deliveries", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.response(200, WebhookDeliverySchema(many=True))
@blp.alt_response(403, schema=ProblemSchema, description="Only admins can do this")
def list_deliveries() -> list[WebhookDelivery]:
    """Recent webhook deliveries

    The latest 50 events: whether each was delivered, how many attempts it took, and the
    last error. Status **dead** means it was given up and copied to the dead-letter table.
    **Admin only.**
    """
    return webhooks.list_deliveries(current_tenant_id())
