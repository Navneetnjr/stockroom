from typing import Any

from flask_smorest import Blueprint

from app.auth import REQUIRES_LOGIN, auth_required, create_token_for, current_user_id
from app.errors import ProblemSchema
from app.extensions import db
from app.models import Tenant, User
from app.schemas.accounts import LoginSchema, RegisterSchema, TokenSchema, UserSchema
from app.services import accounts

blp = Blueprint("auth", __name__, url_prefix="/auth", description="Sign up and log in")


def _token_response(user: User) -> dict[str, Any]:
    return {
        "access_token": create_token_for(user),
        "token_type": "Bearer",
        "user": user,
        "tenant": db.session.get(Tenant, user.tenant_id),
    }


@blp.route("/register", methods=["POST"])
@blp.arguments(RegisterSchema)
@blp.response(201, TokenSchema)
@blp.alt_response(409, schema=ProblemSchema, description="Email already registered")
def register(data: dict[str, str]) -> dict[str, Any]:
    """Register a new shop

    Creates a tenant (shop) and its first user as **admin**, and returns a login token.
    """
    admin = accounts.register_tenant(data["shop_name"], data["email"], data["password"])
    return _token_response(admin)


@blp.route("/login", methods=["POST"])
@blp.arguments(LoginSchema)
@blp.response(200, TokenSchema)
@blp.alt_response(401, schema=ProblemSchema, description="Wrong email or password")
def login(data: dict[str, str]) -> dict[str, Any]:
    """Log in

    Returns a token. On /docs, click **Authorize** and paste the `access_token`.
    """
    user = accounts.authenticate(data["email"], data["password"])
    return _token_response(user)


@blp.route("/me", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required()
@blp.response(200, UserSchema)
@blp.alt_response(401, schema=ProblemSchema, description="Missing, invalid or expired token")
def me() -> User | None:
    """Who am I?

    Shows the user the token belongs to.
    """
    return db.session.get(User, current_user_id())
