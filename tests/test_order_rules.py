"""Unit tests for the order business rules: no HTTP, no database rows needed."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.errors import InvalidCursorError, InvalidTransitionError
from app.models import Order
from app.services.orders import (
    decode_cursor,
    encode_cursor,
    ensure_transition_allowed,
    line_total,
    merge_lines,
)

ALLOWED = [
    ("draft", "confirmed"),
    ("draft", "cancelled"),
    ("confirmed", "shipped"),
    ("confirmed", "cancelled"),
    ("shipped", "delivered"),
]

NOT_ALLOWED = [
    ("draft", "shipped"),  # can't skip a step
    ("draft", "delivered"),
    ("confirmed", "draft"),  # can't go back
    ("shipped", "cancelled"),  # too late to cancel
    ("delivered", "cancelled"),
    ("cancelled", "confirmed"),  # final
    ("draft", "draft"),
]


@pytest.mark.parametrize(("current", "new"), ALLOWED)
def test_allowed_transitions(current: str, new: str) -> None:
    ensure_transition_allowed(current, new)  # no error


@pytest.mark.parametrize(("current", "new"), NOT_ALLOWED)
def test_forbidden_transitions(current: str, new: str) -> None:
    with pytest.raises(InvalidTransitionError):
        ensure_transition_allowed(current, new)


def test_final_status_error_says_nothing_is_allowed() -> None:
    with pytest.raises(InvalidTransitionError, match="nothing, it is final"):
        ensure_transition_allowed("delivered", "shipped")


def test_line_total_is_exact() -> None:
    # With floats, 0.1 * 3 is 0.30000000000000004; with Decimal it is exact
    assert line_total(Decimal("0.10"), 3) == Decimal("0.30")
    assert line_total(Decimal("499.99"), 2) == Decimal("999.98")


def test_merge_lines_adds_up_repeated_products() -> None:
    lines = [
        {"product_id": 1, "quantity": 2},
        {"product_id": 2, "quantity": 1},
        {"product_id": 1, "quantity": 3},
    ]

    assert merge_lines(lines) == {1: 5, 2: 1}


def test_cursor_round_trip() -> None:
    order = Order(id=42, created_at=datetime(2026, 10, 14, 10, 30, 0, 123456, tzinfo=UTC))

    assert decode_cursor(encode_cursor(order)) == (order.created_at, 42)


@pytest.mark.parametrize("cursor", ["not-base64!!", "aGVsbG8=", "e30="])
def test_broken_cursor_raises(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)
