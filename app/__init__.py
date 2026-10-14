from collections.abc import Mapping
from typing import Any

from flask import Flask

from app import models  # noqa: F401  (registers every table with SQLAlchemy)
from app.api import auth, health, products, users
from app.auth import init_auth
from app.config import Config
from app.errors import StockroomApi, register_error_handlers
from app.extensions import db

REQUIRED_SETTINGS = {
    "SQLALCHEMY_DATABASE_URI": "DATABASE_URL",
    "JWT_SECRET_KEY": "JWT_SECRET_KEY",
}


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    """Build and configure the Flask application.

    `overrides` lets tests swap settings, e.g. point at the test database.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    for setting, env_var in REQUIRED_SETTINGS.items():
        if not app.config.get(setting):
            raise RuntimeError(f"{env_var} is not set. Copy .env.example to .env and fill it in.")

    db.init_app(app)
    init_auth(app)

    # The Api object collects every endpoint into the OpenAPI spec and the /docs page
    api = StockroomApi(app)
    for module in (health, auth, users, products):
        api.register_blueprint(module.blp)
    register_error_handlers(app)

    return app
