from flask.testing import FlaskClient

from app.errors import PROBLEM_CONTENT_TYPE
from tests.helpers import (
    add_staff,
    auth_header,
    create_product,
    place_order,
    register_shop,
    set_status,
    stock_of,
)

# --- Placing orders -------------------------------------------------------------------------


def test_place_order_takes_stock_and_records_it(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, sku="SHOE", price="499.00", initial_stock=10)
    sock = create_product(client, admin, sku="SOCK", price="49.50", initial_stock=20)

    response = place_order(client, admin, (shoe["id"], 2), (sock["id"], 3))

    assert response.status_code == 201
    order = response.get_json()
    assert order["status"] == "draft"
    assert order["total"] == "1146.50"  # 2 x 499.00 + 3 x 49.50
    assert [(line["quantity"], line["unit_price"]) for line in order["lines"]] == [
        (2, "499.00"),
        (3, "49.50"),
    ]
    assert stock_of(client, admin, shoe["id"]) == 8
    assert stock_of(client, admin, sock["id"]) == 17
    history = client.get(
        f"/products/{shoe['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert history[-1] == history[-1] | {
        "quantity": -2,
        "reason": "order_placed",
        "order_id": order["id"],
    }


def test_staff_can_place_orders(client: FlaskClient) -> None:
    admin = register_shop(client)
    staff = add_staff(client, admin)
    shoe = create_product(client, admin)

    assert place_order(client, staff, (shoe["id"], 1)).status_code == 201


def test_short_line_rejects_the_whole_order(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, sku="SHOE", initial_stock=10)
    sock = create_product(client, admin, sku="SOCK", initial_stock=1)

    response = place_order(client, admin, (shoe["id"], 2), (sock["id"], 5))

    assert response.status_code == 409
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.get_json()["type"] == "/problems/insufficient-stock"
    assert "SOCK has 1, 5 requested" in response.get_json()["detail"]
    # All or nothing: the shoe line did not take stock either, and no order exists
    assert stock_of(client, admin, shoe["id"]) == 10
    assert client.get("/orders", headers=auth_header(admin)).get_json()["items"] == []


def test_repeated_product_lines_are_added_up(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)

    response = place_order(client, admin, (shoe["id"], 2), (shoe["id"], 3))

    assert response.get_json()["lines"][0]["quantity"] == 5
    assert stock_of(client, admin, shoe["id"]) == 5


def test_unknown_deleted_or_other_shops_product_returns_404(client: FlaskClient) -> None:
    shoe_shop = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    bread = create_product(client, bakery, sku="BREAD")
    old = create_product(client, shoe_shop, sku="OLD")
    client.delete(f"/products/{old['id']}", headers=auth_header(shoe_shop))

    for product_id in (9999, bread["id"], old["id"]):
        response = place_order(client, shoe_shop, (product_id, 1))
        assert response.status_code == 404, product_id


def test_invalid_order_body_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)

    empty = client.post("/orders", json={"lines": []}, headers=auth_header(admin))
    zero = place_order(client, admin, (1, 0))

    assert empty.status_code == 422
    assert zero.status_code == 422


def test_later_price_change_does_not_change_old_orders(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, price="499.00")
    order = place_order(client, admin, (shoe["id"], 1)).get_json()

    client.patch(f"/products/{shoe['id']}", json={"price": "999.00"}, headers=auth_header(admin))

    again = client.get(f"/orders/{order['id']}", headers=auth_header(admin)).get_json()
    assert again["lines"][0]["unit_price"] == "499.00"
    assert again["total"] == "499.00"


# --- Listing orders (cursor pagination) -----------------------------------------------------


def test_orders_are_listed_newest_first_page_by_page(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=100)
    ids = [place_order(client, admin, (shoe["id"], 1)).get_json()["id"] for _ in range(5)]

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        url = "/orders?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = client.get(url, headers=auth_header(admin)).get_json()
        seen += [order["id"] for order in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert pages == 3  # 2 + 2 + 1
    assert seen == list(reversed(ids))  # newest first, each order exactly once


def test_orders_can_be_filtered_by_status(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)
    first = place_order(client, admin, (shoe["id"], 1)).get_json()
    place_order(client, admin, (shoe["id"], 1))
    set_status(client, admin, first["id"], "confirmed")

    page = client.get("/orders?status=confirmed", headers=auth_header(admin)).get_json()

    assert [order["id"] for order in page["items"]] == [first["id"]]


def test_broken_cursor_returns_400(client: FlaskClient) -> None:
    admin = register_shop(client)

    response = client.get("/orders?cursor=garbage", headers=auth_header(admin))

    assert response.status_code == 400
    assert response.get_json()["type"] == "/problems/invalid-cursor"


def test_other_shops_orders_are_invisible(client: FlaskClient) -> None:
    shoe_shop = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    shoe = create_product(client, shoe_shop)
    order = place_order(client, shoe_shop, (shoe["id"], 1)).get_json()

    listing = client.get("/orders", headers=auth_header(bakery)).get_json()
    detail = client.get(f"/orders/{order['id']}", headers=auth_header(bakery))
    change = set_status(client, bakery, order["id"], "cancelled")

    assert listing["items"] == []
    assert detail.status_code == 404
    assert change.status_code == 404
    assert stock_of(client, shoe_shop, shoe["id"]) == 9  # the bakery cancelled nothing


# --- Status changes (state machine) ---------------------------------------------------------


def test_order_goes_through_all_steps(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)
    order = place_order(client, admin, (shoe["id"], 1)).get_json()

    for status in ("confirmed", "shipped", "delivered"):
        response = set_status(client, admin, order["id"], status)
        assert response.status_code == 200
        assert response.get_json()["status"] == status


def test_skipping_a_step_returns_409(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)
    order = place_order(client, admin, (shoe["id"], 1)).get_json()

    response = set_status(client, admin, order["id"], "shipped")

    assert response.status_code == 409
    assert response.get_json()["type"] == "/problems/invalid-transition"
    assert "draft cannot become shipped" in response.get_json()["detail"]


def test_cancelling_puts_stock_back(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)
    order = place_order(client, admin, (shoe["id"], 4)).get_json()
    set_status(client, admin, order["id"], "confirmed")

    response = set_status(client, admin, order["id"], "cancelled")

    assert response.get_json()["status"] == "cancelled"
    assert stock_of(client, admin, shoe["id"]) == 10
    history = client.get(
        f"/products/{shoe['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert [(m["quantity"], m["reason"]) for m in history] == [
        (10, "initial"),
        (-4, "order_placed"),
        (4, "order_cancelled"),
    ]


def test_shipped_orders_cannot_be_cancelled(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin)
    order = place_order(client, admin, (shoe["id"], 1)).get_json()
    set_status(client, admin, order["id"], "confirmed")
    set_status(client, admin, order["id"], "shipped")

    response = set_status(client, admin, order["id"], "cancelled")

    assert response.status_code == 409
    assert stock_of(client, admin, shoe["id"]) == 9  # stock stays sold


def test_cancelling_still_works_after_the_product_was_deleted(client: FlaskClient) -> None:
    admin = register_shop(client)
    shoe = create_product(client, admin, initial_stock=10)
    order = place_order(client, admin, (shoe["id"], 3)).get_json()
    client.delete(f"/products/{shoe['id']}", headers=auth_header(admin))

    response = set_status(client, admin, order["id"], "cancelled")

    assert response.status_code == 200
