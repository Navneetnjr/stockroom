from collections.abc import Mapping
from typing import Any

from flask import Flask

from app import models  # noqa: F401  (registers every table with SQLAlchemy)
from app.api.health import health_bp
from app.config import Config
from app.extensions import db


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    """Build and configure the Flask application.

    `overrides` lets tests swap settings, e.g. point at the test database.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    db.init_app(app)
    app.register_blueprint(health_bp)
    return app
