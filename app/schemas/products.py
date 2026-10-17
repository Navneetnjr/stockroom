from decimal import Decimal
from typing import Any

from marshmallow import Schema, ValidationError, fields, validate, validates_schema

from app.models import MovementReason

# Numeric(12, 2) in the database holds at most 9,999,999,999.99
PRICE_RULES = validate.Range(min=Decimal("0"), max=Decimal("9999999999.99"))


def _not_zero(value: int) -> None:
    if value == 0:
        raise ValidationError("Quantity cannot be 0.")


class ProductSchema(Schema):
    id = fields.Integer(dump_only=True)
    sku = fields.String(dump_only=True)
    name = fields.String(dump_only=True)
    # Money is sent as a string ("499.00") so it is never rounded like a float
    price = fields.Decimal(places=2, as_string=True, dump_only=True)
    stock_on_hand = fields.Integer(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class CreateProductSchema(Schema):
    sku = fields.String(required=True, validate=validate.Length(min=1, max=64))
    name = fields.String(required=True, validate=validate.Length(min=1, max=200))
    price = fields.Decimal(places=2, required=True, validate=PRICE_RULES)
    initial_stock = fields.Integer(load_default=0, validate=validate.Range(min=0))


class UpdateProductSchema(Schema):
    sku = fields.String(validate=validate.Length(min=1, max=64))
    name = fields.String(validate=validate.Length(min=1, max=200))
    price = fields.Decimal(places=2, validate=PRICE_RULES)

    @validates_schema
    def at_least_one_field(self, data: dict[str, Any], **kwargs: Any) -> None:
        if not data:
            raise ValidationError("Send at least one field to change: sku, name or price.")


class StockMovementSchema(Schema):
    id = fields.Integer(dump_only=True)
    product_id = fields.Integer(dump_only=True)
    quantity = fields.Integer(dump_only=True, metadata={"description": "+ in, - out"})
    reason = fields.String(dump_only=True)
    order_id = fields.Integer(dump_only=True, allow_none=True)
    created_at = fields.DateTime(dump_only=True)


class CreateStockMovementSchema(Schema):
    quantity = fields.Integer(
        required=True,
        validate=_not_zero,
        metadata={"description": "Positive to add stock, negative to remove it"},
    )
    reason = fields.String(
        load_default=MovementReason.RESTOCK.value,
        validate=validate.OneOf([MovementReason.RESTOCK.value, MovementReason.ADJUSTMENT.value]),
    )


class StockChangeSchema(Schema):
    movement = fields.Nested(StockMovementSchema)
    product = fields.Nested(ProductSchema)
