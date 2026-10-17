"""All database tables. Importing this package registers every model with SQLAlchemy."""

from app.models.idempotency_key import IdempotencyKey
from app.models.order import Order, OrderLine, OrderStatus
from app.models.product import Product
from app.models.stock_movement import MovementReason, StockMovement
from app.models.tenant import Tenant
from app.models.user import User, UserRole

__all__ = [
    "IdempotencyKey",
    "MovementReason",
    "Order",
    "OrderLine",
    "OrderStatus",
    "Product",
    "StockMovement",
    "Tenant",
    "User",
    "UserRole",
]
