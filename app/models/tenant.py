from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base
from app.models.mixins import TimestampMixin


class Tenant(TimestampMixin, Base):
    """A shop (company) that uses Stockroom. Every other row belongs to one tenant."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Where order webhooks are sent, and the secret used to sign them
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_secret: Mapped[str | None] = mapped_column(String(100))
