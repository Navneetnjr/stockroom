import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app


@pytest.fixture
def app() -> Flask:
    """A fresh app for every test."""
    app = create_app()
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A fake browser that sends requests to the app without starting a server."""
    return app.test_client()
