"""CSV import tests. Celery runs in "eager" mode here, so each job runs inside the request."""

import io

import pytest
from flask import Flask
from flask.testing import FlaskClient
from kombu.exceptions import OperationalError
from sqlalchemy.exc import IntegrityError
from werkzeug.test import TestResponse

from app.services import imports
from tests.helpers import add_staff, auth_header, create_product, register_shop

GOOD_FILE = "sku,name,price,stock\nRED-SHOE,Red Shoe,499.00,10\nSOCK,Wool Sock,49.50,\n"


def upload(client: FlaskClient, token: str, text: str, filename: str = "p.csv") -> TestResponse:
    return client.post(
        "/products/imports",
        data={"file": (io.BytesIO(text.encode()), filename)},
        content_type="multipart/form-data",
        headers=auth_header(token),
    )


def products_by_sku(client: FlaskClient, token: str) -> dict[str, dict[str, object]]:
    listing = client.get("/products", headers=auth_header(token)).get_json()
    return {product["sku"]: product for product in listing}


def test_import_returns_202_and_creates_products(client: FlaskClient) -> None:
    admin = register_shop(client)

    response = upload(client, admin, GOOD_FILE)

    assert response.status_code == 202
    job = response.get_json()
    assert response.headers["Location"] == f"/products/imports/{job['id']}"
    assert job["status"] == "completed"  # without Redis the job already ran
    assert (job["total_rows"], job["succeeded_rows"], job["failed_rows"]) == (2, 2, 0)
    products = products_by_sku(client, admin)
    assert products["RED-SHOE"]["stock_on_hand"] == 10
    assert products["SOCK"]["price"] == "49.50"
    assert products["SOCK"]["stock_on_hand"] == 0  # empty stock column: not touched
    history = client.get(
        f"/products/{products['RED-SHOE']['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert [(m["quantity"], m["reason"]) for m in history] == [(10, "import")]


def test_bad_rows_are_reported_and_good_rows_still_imported(client: FlaskClient) -> None:
    admin = register_shop(client)
    text = (
        "sku,name,price,stock\n"
        "OK-1,Fine,10.00,5\n"
        "BAD-PRICE,Broken,abc,1\n"
        ",No SKU,5.00,\n"
        "NEG,Negative stock,5.00,-3\n"
        "OK-2,Also fine,20.00,\n"
    )

    job = upload(client, admin, text).get_json()

    assert (job["succeeded_rows"], job["failed_rows"]) == (2, 3)
    assert [(e["row"], e["sku"]) for e in job["errors"]] == [
        (3, "BAD-PRICE"),
        (4, None),
        (5, "NEG"),
    ]
    assert "price" in job["errors"][0]["error"]
    assert sorted(products_by_sku(client, admin)) == ["OK-1", "OK-2"]


def test_row_that_clashes_in_the_database_is_reported(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = register_shop(client)
    real_import_row = imports._import_row

    def clash_on_sock(tenant_id: int, row: dict[str, str]) -> None:
        if row["sku"] == "SOCK":  # e.g. another import created this SKU at the same moment
            raise IntegrityError("INSERT INTO products ...", {}, Exception("duplicate key"))
        real_import_row(tenant_id, row)

    monkeypatch.setattr(imports, "_import_row", clash_on_sock)

    job = upload(client, admin, GOOD_FILE).get_json()

    assert (job["succeeded_rows"], job["failed_rows"]) == (1, 1)
    assert job["errors"][0]["error"].startswith("Conflicts with another product")


def test_existing_products_are_updated_and_stock_is_set(client: FlaskClient) -> None:
    admin = register_shop(client)
    create_product(client, admin, sku="RED-SHOE", price="400.00", initial_stock=4)

    upload(client, admin, "sku,name,price,stock\nRED-SHOE,Red Shoe v2,450.00,10\n")

    shoe = products_by_sku(client, admin)["RED-SHOE"]
    assert (shoe["name"], shoe["price"], shoe["stock_on_hand"]) == ("Red Shoe v2", "450.00", 10)
    history = client.get(
        f"/products/{shoe['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert [(m["quantity"], m["reason"]) for m in history] == [(4, "initial"), (6, "import")]


def test_importing_the_same_file_twice_changes_nothing(client: FlaskClient) -> None:
    admin = register_shop(client)
    upload(client, admin, GOOD_FILE)
    before = products_by_sku(client, admin)

    upload(client, admin, GOOD_FILE)

    after = products_by_sku(client, admin)
    assert {sku: p["stock_on_hand"] for sku, p in after.items()} == {"RED-SHOE": 10, "SOCK": 0}
    assert len(after) == len(before)
    history = client.get(
        f"/products/{after['RED-SHOE']['id']}/stock-movements", headers=auth_header(admin)
    ).get_json()
    assert len(history) == 1  # no second stock movement


def test_running_a_finished_job_again_does_nothing(app: Flask, client: FlaskClient) -> None:
    admin = register_shop(client)
    job = upload(client, admin, GOOD_FILE).get_json()

    with app.app_context():
        imports.process_import(job["id"])  # e.g. a retried message

    assert len(products_by_sku(client, admin)) == 2
    again = client.get(f"/products/imports/{job['id']}", headers=auth_header(admin)).get_json()
    assert again["succeeded_rows"] == 2


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"name,price\nShoe,1.00\n", "Missing columns: sku"),
        ("sku,name,price\n".encode("utf-16"), "UTF-8"),
    ],
)
def test_wrong_file_returns_400(client: FlaskClient, content: bytes, expected: str) -> None:
    admin = register_shop(client)

    response = client.post(
        "/products/imports",
        data={"file": (io.BytesIO(content), "p.csv")},
        content_type="multipart/form-data",
        headers=auth_header(admin),
    )

    assert response.status_code == 400
    assert response.get_json()["type"] == "/problems/invalid-import-file"
    assert expected in response.get_json()["detail"]


def test_too_many_rows_returns_400(
    app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = register_shop(client)
    monkeypatch.setitem(app.config, "IMPORT_MAX_ROWS", 1)

    response = upload(client, admin, GOOD_FILE)  # 2 rows

    assert response.status_code == 400
    assert "limit is 1" in response.get_json()["detail"]


def test_missing_file_returns_422(client: FlaskClient) -> None:
    admin = register_shop(client)

    response = client.post(
        "/products/imports", data={}, content_type="multipart/form-data", headers=auth_header(admin)
    )

    assert response.status_code == 422


def test_staff_cannot_import_and_shops_cannot_see_each_others_jobs(client: FlaskClient) -> None:
    shoe_shop = register_shop(client, "Shoe Shop", "owner@shoe.test")
    bakery = register_shop(client, "Bakery", "owner@bakery.test")
    staff = add_staff(client, shoe_shop)
    job = upload(client, shoe_shop, GOOD_FILE).get_json()

    assert upload(client, staff, GOOD_FILE).status_code == 403
    assert (
        client.get(f"/products/imports/{job['id']}", headers=auth_header(bakery)).status_code == 404
    )


def test_queue_down_returns_503_and_marks_the_job_failed(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = register_shop(client)

    def broken_delay(*args: object, **kwargs: object) -> None:
        raise OperationalError("Redis is down")

    monkeypatch.setattr(imports.import_products_task, "delay", broken_delay)

    response = upload(client, admin, GOOD_FILE)

    assert response.status_code == 503
    assert products_by_sku(client, admin) == {}
    job = client.get("/products/imports/1", headers=auth_header(admin)).get_json()
    assert job["status"] == "failed"
