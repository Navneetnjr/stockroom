from collections.abc import Mapping
from typing import Any, cast

from flask import Blueprint, Flask

from app import models  # noqa: F401  (registers every table with SQLAlchemy)
from app.api import auth, health, orders, products, users, webhooks
from app.auth import init_auth
from app.cache import init_redis
from app.celery_setup import celery_init_app
from app.config import Config
from app.errors import StockroomApi, register_error_handlers
from app.extensions import db
from app.observability import configure_logging, enable_slow_query_logging, init_request_logging
from app.rate_limiting import init_rate_limiting, limiter

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

    configure_logging(app.config["LOG_LEVEL"])
    init_request_logging(app)
    enable_slow_query_logging(app.config["SLOW_QUERY_MS"])

    db.init_app(app)
    init_auth(app)
    init_redis(app)
    init_rate_limiting(app)
    celery_init_app(app)

    # The Api object collects every endpoint into the OpenAPI spec and the /docs page
    api = StockroomApi(app)
    for module in (health, auth, users, products, orders, webhooks):
        api.register_blueprint(module.blp)
    register_error_handlers(app)

    # Health checks and the docs page are never rate limited (monitors call them often)
    limiter.exempt(health.blp)
    limiter.exempt(cast(Blueprint, app.blueprints["api-docs"]))

    return app
