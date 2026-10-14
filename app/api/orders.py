from typing import Any

from flask_smorest import Blueprint

from app.auth import REQUIRES_LOGIN, auth_required, current_tenant_id, current_user_id
from app.errors import ProblemSchema
from app.idempotency import ACCEPTS_IDEMPOTENCY_KEY, idempotent
from app.models import Order
from app.schemas.orders import (
    CreateOrderSchema,
    OrderListQuerySchema,
    OrderPageSchema,
    OrderSchema,
    StatusChangeSchema,
)
from app.services import orders

blp = Blueprint("orders", __name__, url_prefix="/orders", description="Customer orders")


@blp.route("", methods=["POST"])
@blp.doc(**REQUIRES_LOGIN, **ACCEPTS_IDEMPOTENCY_KEY)
@auth_required()
@idempotent
@blp.arguments(CreateOrderSchema)
@blp.response(201, OrderSchema)
@blp.alt_response(404, schema=ProblemSchema, description="A product does not exist")
@blp.alt_response(409, schema=ProblemSchema, description="Not enough stock")
def place_order(data: dict[str, Any]) -> Order:
    """Place an order

    Checks stock, creates the order (status **draft**) and takes the stock, all in one
    transaction. If any line is short of stock, nothing is changed.
    """
    return orders.place_order(current_tenant_id(), current_user_id(), data["lines"])


@blp.route("", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.arguments(OrderListQuerySchema, location="query")
@blp.response(200, OrderPageSchema)
@blp.alt_response(400, schema=ProblemSchema, description="Invalid cursor")
def list_orders(query: dict[str, Any]) -> dict[str, Any]:
    """List orders

    Newest first, one page at a time. To get the next page, pass the `next_cursor`
    from this page as `?cursor=`. Optionally filter by `status`.
    """
    items, next_cursor = orders.list_orders(
        current_tenant_id(), query["limit"], query.get("cursor"), query.get("status")
    )
    return {"items": items, "next_cursor": next_cursor}


@blp.route("/<int:order_id>", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.response(200, OrderSchema)
@blp.alt_response(404, schema=ProblemSchema, description="No such order in your shop")
def get_order(order_id: int) -> Order:
    """Get an order"""
    return orders.get_order(current_tenant_id(), order_id)


@blp.route("/<int:order_id>/transitions", methods=["POST"])
@blp.doc(**REQUIRES_LOGIN, **ACCEPTS_IDEMPOTENCY_KEY)
@auth_required()
@idempotent
@blp.arguments(StatusChangeSchema)
@blp.response(200, OrderSchema)
@blp.alt_response(404, schema=ProblemSchema, description="No such order in your shop")
@blp.alt_response(409, schema=ProblemSchema, description="This status change is not allowed")
def change_status(data: dict[str, str], order_id: int) -> Order:
    """Change an order's status

    Allowed: draft → confirmed → shipped → delivered, and **cancelled** from draft or
    confirmed. Cancelling puts the stock back.
    """
    return orders.change_status(current_tenant_id(), order_id, data["status"])
