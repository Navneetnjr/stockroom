from typing import NoReturn

import pytest
from flask.testing import FlaskClient
from sqlalchemy.exc import OperationalError

from app import create_app
from app.extensions import db
from tests.helpers import settings_for_tests


def test_healthz_returns_ok(client: FlaskClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readyz_returns_ok_when_database_is_up(client: FlaskClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "up"}


def test_readyz_returns_503_when_database_is_down(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_execute(*args: object, **kwargs: object) -> NoReturn:
        raise OperationalError("SELECT 1", {}, Exception("database is down"))

    # Pretend the database is broken for this one test
    monkeypatch.setattr(db.session, "execute", broken_execute)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable", "database": "down"}


def test_create_app_fails_without_database_url() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        create_app({"SQLALCHEMY_DATABASE_URI": None})


def test_create_app_fails_without_jwt_secret() -> None:
    # Give a database URL so only the missing secret is tested (CI has no .env file)
    settings = settings_for_tests() | {"JWT_SECRET_KEY": None}

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is not set"):
        create_app(settings)
