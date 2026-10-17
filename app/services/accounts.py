"""Tenants and users: sign-up, login and adding users."""

from sqlalchemy import select

from app.auth import hash_password, password_matches
from app.errors import ConflictError, UnauthorizedError
from app.extensions import db
from app.models import Tenant, User, UserRole
from app.services.common import commit_or_conflict


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_taken(email: str) -> bool:
    return db.session.scalar(select(User.id).where(User.email == email)) is not None


def register_tenant(shop_name: str, email: str, password: str) -> User:
    """Create a new tenant and its first user, who is an admin."""
    email = _normalize_email(email)
    if _email_taken(email):
        raise ConflictError(f"The email {email} is already registered.")

    tenant = Tenant(name=shop_name.strip())
    db.session.add(tenant)
    db.session.flush()  # send the INSERT now so tenant.id has a value

    admin = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
    )
    db.session.add(admin)
    commit_or_conflict(f"The email {email} is already registered.")
    return admin


def create_user(tenant_id: int, email: str, password: str, role: str) -> User:
    """Add a user to an existing tenant (done by that tenant's admin)."""
    email = _normalize_email(email)
    if _email_taken(email):
        raise ConflictError(f"The email {email} is already registered.")

    user = User(tenant_id=tenant_id, email=email, password_hash=hash_password(password), role=role)
    db.session.add(user)
    commit_or_conflict(f"The email {email} is already registered.")
    return user


def authenticate(email: str, password: str) -> User:
    """Return the user if the email and password are right."""
    user = db.session.scalar(select(User).where(User.email == _normalize_email(email)))
    if user is None or not password_matches(user.password_hash, password):
        # Same message for both cases, so nobody can probe which emails exist
        raise UnauthorizedError("Invalid email or password.")
    return user


def list_users(tenant_id: int) -> list[User]:
    return list(
        db.session.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id))
    )
