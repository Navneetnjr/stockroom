"""Login: password hashing, JWT tokens, and checks for who is calling."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Flask, Response
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request
from werkzeug.security import check_password_hash, generate_password_hash

from app.errors import ForbiddenError, problem_response
from app.extensions import jwt
from app.models import User

# Tells /docs that an endpoint needs the "Authorize" token: use as @blp.doc(**REQUIRES_LOGIN)
REQUIRES_LOGIN: dict[str, Any] = {"security": [{"bearerAuth": []}]}


def hash_password(password: str) -> str:
    """Scramble a password one way, so the real password is never stored."""
    return generate_password_hash(password)


def password_matches(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def create_token_for(user: User) -> str:
    """A signed token that says who the user is, their tenant and their role."""
    token: str = create_access_token(
        identity=str(user.id),
        additional_claims={"tenant_id": user.tenant_id, "role": user.role},
    )
    return token


def current_user_id() -> int:
    return int(get_jwt_identity())


def current_tenant_id() -> int:
    """The tenant of the logged-in user. Every query must be filtered by this."""
    return int(get_jwt()["tenant_id"])


def auth_required[**P, R](*roles: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Require a valid login token; if roles are given, the user must have one of them."""

    def decorator(view: Callable[P, R]) -> Callable[P, R]:
        @wraps(view)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            verify_jwt_in_request()
            if roles and get_jwt().get("role") not in roles:
                raise ForbiddenError(f"This action needs one of these roles: {', '.join(roles)}.")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _unauthorized(detail: str) -> Response:
    response = problem_response(401, "Unauthorized", detail)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


def init_auth(app: Flask) -> None:
    """Set up JWT tokens and send token problems as RFC 9457 responses."""
    jwt.init_app(app)

    @jwt.unauthorized_loader
    def missing_token(reason: str) -> Response:
        return _unauthorized(f"{reason}. Log in and send 'Authorization: Bearer <token>'.")

    @jwt.invalid_token_loader
    def invalid_token(reason: str) -> Response:
        return _unauthorized(f"The token is not valid: {reason}.")

    @jwt.expired_token_loader
    def expired_token(jwt_header: dict[str, Any], jwt_payload: dict[str, Any]) -> Response:
        return _unauthorized("The token has expired. Log in again.")
