from enum import StrEnum

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TenantScopedMixin, TimestampMixin


class UserRole(StrEnum):
    ADMIN = "admin"
    STAFF = "staff"


class User(TenantScopedMixin, TimestampMixin, Base):
    """A person who logs in for a tenant, either as admin or staff."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'staff')", name="role_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique across all tenants, so a login only needs email + password
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.STAFF)
