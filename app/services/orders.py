"""Orders: placing them without overselling, listing them page by page, and moving them
through their steps (draft -> confirmed -> shipped -> delivered, or cancelled)."""

import base64
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, literal, select, tuple_
from sqlalchemy.orm import selectinload

from app.cache import invalidate_products
from app.errors import (
    InsufficientStockError,
    InvalidCursorError,
    InvalidTransitionError,
    NotFoundError,
)
from app.extensions import db
from app.models import MovementReason, Order, OrderLine, OrderStatus, Product
from app.services.products import apply_stock_change

# The order state machine: which statuses an order may move to from each status.
# Cancelling is only possible before the order has shipped.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


# --- Pure business rules (no database, easy to unit test) ----------------------------------


def ensure_transition_allowed(current: str, new: str) -> None:
    """Raise a 409 if an order may not move from `current` to `new`."""
    allowed = ALLOWED_TRANSITIONS[current]
    if new not in allowed:
        options = ", ".join(sorted(allowed)) or "nothing, it is final"
        raise InvalidTransitionError(
            f"An order that is {current} cannot become {new}. It can become: {options}."
        )


def line_total(unit_price: Decimal, quantity: int) -> Decimal:
    return unit_price * quantity


def merge_lines(lines: Iterable[dict[str, int]]) -> dict[int, int]:
    """Add up quantities when the same product appears on several lines."""
    quantities: dict[int, int] = {}
    for line in lines:
        quantities[line["product_id"]] = quantities.get(line["product_id"], 0) + line["quantity"]
    return quantities


def encode_cursor(order: Order) -> str:
    """A bookmark pointing just after this order in the newest-first list."""
    position = {"created_at": order.created_at.isoformat(), "id": order.id}
    return base64.urlsafe_b64encode(json.dumps(position).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        position = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(position["created_at"]), int(position["id"])
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidCursorError(
            "The cursor is not valid. Use the next_cursor value from the previous page."
        ) from error


# --- Database work --------------------------------------------------------------------------


def _orders(tenant_id: int) -> Select[Order]:
    """Base query: this tenant's orders, with their lines loaded in one extra query."""
    return select(Order).where(Order.tenant_id == tenant_id).options(selectinload(Order.lines))


def _lock_products(
    tenant_id: int, product_ids: Iterable[int], *, include_deleted: bool = False
) -> dict[int, Product]:
    """Lock the products' rows with SELECT ... FOR UPDATE.

    Rows are always locked in id order, so two orders can never wait for each other forever
    (a deadlock).
    """
    query = (
        select(Product)
        .where(Product.tenant_id == tenant_id, Product.id.in_(list(product_ids)))
        .order_by(Product.id)
        .with_for_update()
        .execution_options(populate_existing=True)  # read the latest stock after locking
    )
    if not include_deleted:
        query = query.where(Product.deleted_at.is_(None))
    return {product.id: product for product in db.session.scalars(query)}


def get_order(tenant_id: int, order_id: int, *, lock: bool = False) -> Order:
    """Find one order, or raise 404 (also for other tenants' orders)."""
    query = _orders(tenant_id).where(Order.id == order_id)
    if lock:
        query = query.with_for_update(of=Order).execution_options(populate_existing=True)
    order = db.session.scalar(query)
    if order is None:
        raise NotFoundError(f"Order {order_id} was not found.")
    return order


def place_order(tenant_id: int, user_id: int, lines: list[dict[str, int]]) -> Order:
    """Create an order and take its stock, all in one transaction.

    While this runs, the products are locked, so parallel orders queue up one by one
    and stock can never be sold twice.
    """
    quantities = merge_lines(lines)
    products = _lock_products(tenant_id, quantities)

    missing = sorted(set(quantities) - set(products))
    if missing:
        raise NotFoundError(f"Products not found: {', '.join(map(str, missing))}.")

    shortages = [
        f"{products[pid].sku} has {products[pid].stock_on_hand}, {quantity} requested"
        for pid, quantity in quantities.items()
        if products[pid].stock_on_hand < quantity
    ]
    if shortages:
        raise InsufficientStockError("Not enough stock: " + "; ".join(shortages) + ".")

    order = Order(
        tenant_id=tenant_id, created_by_id=user_id, status=OrderStatus.DRAFT, total=Decimal(0)
    )
    db.session.add(order)
    db.session.flush()  # get order.id for the stock movements

    for product_id, quantity in quantities.items():
        product = products[product_id]
        amount = line_total(product.price, quantity)
        order.lines.append(
            OrderLine(
                tenant_id=tenant_id,
                product_id=product_id,
                quantity=quantity,
                unit_price=product.price,
                line_total=amount,
            )
        )
        apply_stock_change(product, -quantity, MovementReason.ORDER_PLACED, order.id)
        order.total += amount

    db.session.commit()  # the order, its lines and its stock movements are saved together
    invalidate_products(tenant_id)  # stock changed, so cached product reads are stale
    return get_order(tenant_id, order.id)


def list_orders(
    tenant_id: int, limit: int, cursor: str | None = None, status: str | None = None
) -> tuple[list[Order], str | None]:
    """One page of orders, newest first, plus the cursor for the next page (None at the end).

    Cursor paging continues "after the last order you saw" instead of skipping N rows,
    so it stays fast on big tables and never shows an order twice when new ones arrive.
    """
    query = _orders(tenant_id).order_by(Order.created_at.desc(), Order.id.desc())
    if status:
        query = query.where(Order.status == status)
    if cursor:
        created_at, order_id = decode_cursor(cursor)
        after = tuple_(literal(created_at, Order.created_at.type), literal(order_id))
        query = query.where(tuple_(Order.created_at, Order.id) < after)

    orders = list(db.session.scalars(query.limit(limit + 1)))  # one extra: is there a next page?
    next_cursor = encode_cursor(orders[limit - 1]) if len(orders) > limit else None
    return orders[:limit], next_cursor


def change_status(tenant_id: int, order_id: int, new_status: str) -> Order:
    """Move an order to a new status. Cancelling puts its stock back."""
    order = get_order(tenant_id, order_id, lock=True)
    ensure_transition_allowed(order.status, new_status)

    if new_status == OrderStatus.CANCELLED:
        products = _lock_products(
            tenant_id, [line.product_id for line in order.lines], include_deleted=True
        )
        for line in order.lines:
            apply_stock_change(
                products[line.product_id], line.quantity, MovementReason.ORDER_CANCELLED, order.id
            )

    order.status = new_status
    db.session.commit()
    if new_status == OrderStatus.CANCELLED:
        invalidate_products(tenant_id)  # stock came back
    return get_order(tenant_id, order_id)
