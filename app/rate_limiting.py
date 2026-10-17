"""Rate limiting with Flask-Limiter: counters live in Redis (or memory without Redis).

Every endpoint has its own counter per tenant, so one busy shop cannot slow down the others,
and a burst on one endpoint does not block the rest. Requests without a login are counted
per IP address instead (this also slows down password guessing on /auth/login).
"""

from flask import Flask, current_app
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from jwt import PyJWTError


def rate_limit_key() -> str:
    """Whose counter a request goes into: the tenant's, or the IP address's."""
    try:
        verify_jwt_in_request(optional=True)
        tenant_id = get_jwt().get("tenant_id")
    except (JWTExtendedException, PyJWTError):
        tenant_id = None  # a bad token is rejected by the endpoint itself
    return f"tenant:{tenant_id}" if tenant_id else f"ip:{get_remote_address()}"


def default_limit() -> str:
    return str(current_app.config["RATE_LIMIT_DEFAULT"])


def auth_limit() -> str:
    """The stricter limit for login and sign-up."""
    return str(current_app.config["RATE_LIMIT_AUTH"])


# Limits are read from the app's settings on each request, so they can be changed per app
limiter = Limiter(key_func=rate_limit_key, default_limits=[default_limit])


def init_rate_limiting(app: Flask) -> None:
    limiter.init_app(app)
