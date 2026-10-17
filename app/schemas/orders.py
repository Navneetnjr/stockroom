from marshmallow import Schema, fields, validate

from app.models import OrderStatus

STATUSES = [status.value for status in OrderStatus]


class OrderLineInSchema(Schema):
    product_id = fields.Integer(required=True)
    quantity = fields.Integer(required=True, validate=validate.Range(min=1, max=10_000))


class CreateOrderSchema(Schema):
    lines = fields.List(
        fields.Nested(OrderLineInSchema), required=True, validate=validate.Length(min=1, max=100)
    )


class OrderLineSchema(Schema):
    id = fields.Integer(dump_only=True)
    product_id = fields.Integer(dump_only=True)
    quantity = fields.Integer(dump_only=True)
    unit_price = fields.Decimal(places=2, as_string=True, dump_only=True)
    line_total = fields.Decimal(places=2, as_string=True, dump_only=True)


class OrderSchema(Schema):
    id = fields.Integer(dump_only=True)
    status = fields.String(dump_only=True)
    total = fields.Decimal(places=2, as_string=True, dump_only=True)
    created_by_id = fields.Integer(dump_only=True)
    lines = fields.List(fields.Nested(OrderLineSchema), dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class OrderListQuerySchema(Schema):
    limit = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    cursor = fields.String(metadata={"description": "next_cursor from the previous page"})
    status = fields.String(validate=validate.OneOf(STATUSES))


class OrderPageSchema(Schema):
    items = fields.List(fields.Nested(OrderSchema))
    next_cursor = fields.String(
        allow_none=True,
        metadata={"description": "Pass as ?cursor= for the next page; null at the end"},
    )


class StatusChangeSchema(Schema):
    status = fields.String(required=True, validate=validate.OneOf(STATUSES))
