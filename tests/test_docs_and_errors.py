import os
from typing import NoReturn

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.errors import PROBLEM_CONTENT_TYPE, ApiError


class OutOfStockError(ApiError):
    status = 409
    title = "Out of stock"
    problem_type = "/problems/out-of-stock"


@pytest.fixture
def app_with_failing_routes() -> Flask:
    """A separate app with two extra routes that fail on purpose."""
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": os.environ["TEST_DATABASE_URL"]})

    @app.get("/raise-api-error")
    def raise_api_error() -> NoReturn:
        raise OutOfStockError("Only 2 left")

    @app.get("/crash")
    def crash() -> NoReturn:
        raise RuntimeError("something broke inside")

    return app


def test_openapi_spec_is_served(client: FlaskClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.get_json()
    assert spec["info"]["title"] == "Stockroom API"
    assert "/healthz" in spec["paths"]
    assert "/readyz" in spec["paths"]


def test_docs_page_is_served(client: FlaskClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert b"swagger" in response.data.lower()


def test_unknown_url_returns_problem_details(client: FlaskClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.content_type == PROBLEM_CONTENT_TYPE
    body = response.get_json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/does-not-exist"
    assert body["detail"]


def test_wrong_method_returns_problem_with_allow_header(client: FlaskClient) -> None:
    response = client.delete("/healthz")

    assert response.status_code == 405
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.get_json()["title"] == "Method Not Allowed"
    assert "GET" in response.headers["Allow"]


def test_api_error_returns_its_own_problem(app_with_failing_routes: Flask) -> None:
    response = app_with_failing_routes.test_client().get("/raise-api-error")

    assert response.status_code == 409
    assert response.content_type == PROBLEM_CONTENT_TYPE
    assert response.get_json() == {
        "type": "/problems/out-of-stock",
        "title": "Out of stock",
        "status": 409,
        "detail": "Only 2 left",
        "instance": "/raise-api-error",
    }


def test_crash_returns_500_without_leaking_details(app_with_failing_routes: Flask) -> None:
    response = app_with_failing_routes.test_client().get("/crash")

    assert response.status_code == 500
    body = response.get_json()
    assert body["title"] == "Internal Server Error"
    assert "something broke inside" not in response.get_data(as_text=True)
