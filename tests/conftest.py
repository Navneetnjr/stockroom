from collections.abc import Iterator

import pytest
from alembic import command
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app import create_app
from app.extensions import Base, db
from tests.helpers import alembic_config, settings_for_tests


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database() -> None:
    """Build the tables in the test database once, by running the real migrations."""
    config = alembic_config()
    command.downgrade(config, "base")  # start from an empty database
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def app() -> Flask:
    """One app for the whole test run, connected to the test database."""
    return create_app(settings_for_tests())


@pytest.fixture(autouse=True)
def _clean_tables(app: Flask) -> Iterator[None]:
    """Empty every table after each test, so tests never see each other's data."""
    yield
    with app.app_context():
        table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
        db.session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        db.session.commit()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A fake browser that sends requests to the app without starting a server."""
    return app.test_client()
