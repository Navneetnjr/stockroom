from flask.testing import FlaskClient

from app.errors import PROBLEM_CONTENT_TYPE
from tests.helpers import add_staff, auth_header, create_product, register_shop

# --- Creating -------------------------------------------------------------------------------


def test_admin_creates_product_with_initial_stock(client: FlaskClient) -> None:
    admin = register_shop(client)

    product = create_product(client, admin)

    assert product["sku"] == "RED-SHOE"
    assert product["price"] == "499.00"  # money comes back as an exact string
    assert product["stock_on_hand"] == 10
    history = client.get(
        f"/products/{product['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert [(m["quantity"], m["reason"]) for m in history] == [(10, "initial")]


def test_product_without_initial_stock_has_empty_history(client: FlaskClient) -> None:
    admin = register_shop(client)

    product = create_product(client, admin, initial_stock=0)

    history = client.get(f"/products/{product['id']}/stock-movements", headers=auth_header(admin))
    assert product["stock_on_hand"] == 0
    assert history.get_json() == []


def test_staff_cannot_create_products_but_can_read_them(client: FlaskClient) -> None:
    admin = register_shop(client)
    staff = add_staff(client, admin)
    product = create_product(client, admin)

    create = client.post(
        "/products",
        json={"sku": "X", "name": "X", "price": "1.00"},
        headers=auth_header(staff),
    )
    listing = client.get("/products", headers=auth_header(staff))
    detail = client.get(f"/products/{product['id']}", headers=auth_header(staff))

    assert create.status_code == 403
    assert listing.status_code == 200
    assert detail.status_code == 200


def test_duplicate_sku_in_same_shop_returns_409_but_other_shop_is_fine(
    client: FlaskClient,
) -> None:
    shoe = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    create_product(client, shoe)

    duplicate = client.post(
        "/products",
        json={"sku": "RED-SHOE", "name": "Again", "price": "1.00"},
        headers=auth_header(shoe),
    )

    assert duplicate.status_code == 409
    assert create_product(client, bakery)["sku"] == "RED-SHOE"


def test_invalid_product_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)

    response = client.post(
        "/products",
        json={"sku": "", "price": "-5", "initial_stock": -1},
        headers=auth_header(admin),
    )

    assert response.status_code == 422
    assert set(response.get_json()["errors"]["json"]) == {"sku", "name", "price", "initial_stock"}


def test_products_need_login(client: FlaskClient) -> None:
    assert client.get("/products").status_code == 401


# --- Reading and tenant isolation -----------------------------------------------------------


def test_list_shows_only_your_shops_active_products(client: FlaskClient) -> None:
    shoe = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    create_product(client, shoe, sku="RED-SHOE")
    deleted = create_product(client, shoe, sku="OLD-SHOE")
    create_product(client, bakery, sku="BREAD")
    client.delete(f"/products/{deleted['id']}", headers=auth_header(shoe))

    response = client.get("/products", headers=auth_header(shoe))

    assert [p["sku"] for p in response.get_json()] == ["RED-SHOE"]


def test_other_shops_product_looks_like_it_does_not_exist(client: FlaskClient) -> None:
    shoe = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    product = create_product(client, shoe)
    url = f"/products/{product['id']}"

    # The bakery can't read, change, delete or restock the shoe shop's product
    responses = [
        client.get(url, headers=auth_header(bakery)),
        client.patch(url, json={"name": "Hacked"}, headers=auth_header(bakery)),
        client.delete(url, headers=auth_header(bakery)),
        client.post(f"{url}/stock-movements", json={"quantity": 5}, headers=auth_header(bakery)),
        client.get(f"{url}/stock-movements", headers=auth_header(bakery)),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404, 404]
    assert client.get(url, headers=auth_header(shoe)).get_json()["name"] == "Red Shoe"


# --- Updating and deleting ------------------------------------------------------------------


def test_admin_updates_name_and_price(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)

    response = client.patch(
        f"/products/{product['id']}",
        json={"name": "Red Running Shoe", "price": 549.5},
        headers=auth_header(admin),
    )

    assert response.status_code == 200
    assert response.get_json()["name"] == "Red Running Shoe"
    assert response.get_json()["price"] == "549.50"
    assert response.get_json()["stock_on_hand"] == 10  # stock is untouched


def test_empty_update_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)

    response = client.patch(f"/products/{product['id']}", json={}, headers=auth_header(admin))

    assert response.status_code == 422


def test_update_to_a_taken_sku_returns_409(client: FlaskClient) -> None:
    admin = register_shop(client)
    create_product(client, admin, sku="RED-SHOE")
    blue = create_product(client, admin, sku="BLUE-SHOE")

    response = client.patch(
        f"/products/{blue['id']}", json={"sku": "RED-SHOE"}, headers=auth_header(admin)
    )

    assert response.status_code == 409


def test_delete_hides_the_product(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)
    url = f"/products/{product['id']}"

    first = client.delete(url, headers=auth_header(admin))
    second = client.delete(url, headers=auth_header(admin))

    assert first.status_code == 204
    assert client.get(url, headers=auth_header(admin)).status_code == 404
    assert second.status_code == 404


# --- Stock movements ------------------------------------------------------------------------


def test_restock_and_adjustment_update_stock_and_history(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)
    url = f"/products/{product['id']}/stock-movements"

    restock = client.post(url, json={"quantity": 5}, headers=auth_header(admin))
    damaged = client.post(
        url, json={"quantity": -3, "reason": "adjustment"}, headers=auth_header(admin)
    )

    assert restock.status_code == 201
    assert restock.get_json()["movement"]["reason"] == "restock"
    assert restock.get_json()["product"]["stock_on_hand"] == 15
    assert damaged.get_json()["product"]["stock_on_hand"] == 12
    history = client.get(url, headers=auth_header(admin)).get_json()
    assert [m["quantity"] for m in history] == [10, 5, -3]
    assert sum(m["quantity"] for m in history) == 12  # the ledger adds up to the stock


def test_removing_more_than_in_stock_returns_409(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)  # 10 in stock

    response = client.post(
        f"/products/{product['id']}/stock-movements",
        json={"quantity": -11, "reason": "adjustment"},
        headers=auth_header(admin),
    )

    assert response.status_code == 409
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.get_json()["type"] == "/problems/insufficient-stock"
    after = client.get(f"/products/{product['id']}", headers=auth_header(admin)).get_json()
    assert after["stock_on_hand"] == 10  # nothing changed


def test_zero_quantity_or_system_reason_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)
    product = create_product(client, admin)
    url = f"/products/{product['id']}/stock-movements"

    zero = client.post(url, json={"quantity": 0}, headers=auth_header(admin))
    system_reason = client.post(
        url, json={"quantity": 1, "reason": "order_placed"}, headers=auth_header(admin)
    )

    assert zero.status_code == 422
    assert system_reason.status_code == 422
