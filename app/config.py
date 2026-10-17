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

    # Redis: product cache and rate-limit counters. Optional: without it the cache is skipped
    # and rate limits are counted in memory (fine for one process, e.g. local development).
    REDIS_URL: str | None = os.environ.get("REDIS_URL")
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "60"))

    # Rate limits, counted per tenant (or per IP address when not logged in) and per endpoint
    RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "300 per minute")
    RATE_LIMIT_AUTH = os.environ.get("RATE_LIMIT_AUTH", "10 per minute")  # login and sign-up
    RATELIMIT_STORAGE_URI = REDIS_URL or "memory://"
    RATELIMIT_KEY_PREFIX = "stockroom"
    RATELIMIT_HEADERS_ENABLED = True  # X-RateLimit-* and Retry-After headers
    RATELIMIT_SWALLOW_ERRORS = True  # if Redis is down, let requests through rather than fail

    # Background jobs (Celery), with Redis as the queue. Without Redis (e.g. local development)
    # jobs run straight away inside the request instead of in a worker ("eager" mode).
    CELERY_BROKER_URL = REDIS_URL or "memory://localhost/"
    CELERY_TASK_ALWAYS_EAGER = (
        os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false" if REDIS_URL else "true").lower()
        == "true"
    )
    # Webhooks: give up after this many attempts, waiting 2 s, 4 s, 8 s, ... in between
    WEBHOOK_MAX_ATTEMPTS = int(os.environ.get("WEBHOOK_MAX_ATTEMPTS", "5"))
    WEBHOOK_BACKOFF_SECONDS = float(os.environ.get("WEBHOOK_BACKOFF_SECONDS", "2"))
    WEBHOOK_TIMEOUT_SECONDS = float(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "5"))
    # How often the stock reconciliation job runs
    RECONCILE_INTERVAL_SECONDS = int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "900"))
    # CSV imports: largest upload and number of rows accepted
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    IMPORT_MAX_ROWS = 10_000

    # Logging: JSON lines on stdout; queries slower than SLOW_QUERY_MS are logged with their SQL
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    SLOW_QUERY_MS = float(os.environ.get("SLOW_QUERY_MS", "200"))

    # How passwords are scrambled (werkzeug format). scrypt is strong but uses ~32 MB per hash;
    # tests switch to a light setting to run fast on small machines.
    PASSWORD_HASH_METHOD = os.environ.get("PASSWORD_HASH_METHOD", "scrypt")

    # Login tokens (JWT): signed with this secret, valid for 8 hours
    JWT_SECRET_KEY: str | None = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
