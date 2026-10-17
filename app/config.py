import os
from datetime import timedelta
from typing import Any

from dotenv import load_dotenv

# Copy values from a local .env file into environment variables (skipped if there is no .env)
load_dotenv()


class Config:
    """App settings, read from environment variables."""

    SQLALCHEMY_DATABASE_URI: str | None = os.environ.get("DATABASE_URL")
    # Check a pooled connection is still alive before using it
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, bool] = {"pool_pre_ping": True}

    # API docs, generated from the code by flask-smorest:
    # the spec is served at /openapi.json and the interactive page at /docs
    API_TITLE = "Stockroom API"
    API_VERSION = "v1"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/"
    OPENAPI_JSON_PATH = "openapi.json"
    OPENAPI_SWAGGER_UI_PATH = "/docs"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/"
    # Adds the "Authorize" button on /docs, where you paste a login token
    API_SPEC_OPTIONS: dict[str, Any] = {
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            }
        }
    }

    # Login tokens (JWT): signed with this secret, valid for 8 hours
    JWT_SECRET_KEY: str | None = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
