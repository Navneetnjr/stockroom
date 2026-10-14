from flask_smorest import Blueprint

from app.auth import REQUIRES_LOGIN, auth_required, current_tenant_id
from app.errors import ProblemSchema
from app.models import User, UserRole
from app.schemas.accounts import CreateUserSchema, UserSchema
from app.services import accounts

blp = Blueprint("users", __name__, url_prefix="/users", description="Users of your shop (admin)")


@blp.route("", methods=["GET"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.response(200, UserSchema(many=True))
@blp.alt_response(403, schema=ProblemSchema, description="Only admins can do this")
def list_users() -> list[User]:
    """List users

    All users of your shop. **Admin only.**
    """
    return accounts.list_users(current_tenant_id())


@blp.route("", methods=["POST"])
@blp.doc(**REQUIRES_LOGIN)
@auth_required(UserRole.ADMIN)
@blp.arguments(CreateUserSchema)
@blp.response(201, UserSchema)
@blp.alt_response(403, schema=ProblemSchema, description="Only admins can do this")
@blp.alt_response(409, schema=ProblemSchema, description="Email already registered")
def create_user(data: dict[str, str]) -> User:
    """Add a user

    Adds a **staff** (default) or **admin** user to your shop. **Admin only.**
    """
    return accounts.create_user(current_tenant_id(), data["email"], data["password"], data["role"])
