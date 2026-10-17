from marshmallow import Schema, fields, validate


class WebhookConfigInSchema(Schema):
    url = fields.Url(required=True, schemes={"http", "https"}, require_tld=False)
    secret = fields.String(
        validate=validate.Length(min=16, max=100),
        metadata={"description": "Optional; a random secret is generated if left out"},
    )


class WebhookConfigSchema(Schema):
    url = fields.String(allow_none=True)
    configured = fields.Boolean()


class WebhookConfigWithSecretSchema(WebhookConfigSchema):
    secret = fields.String(metadata={"description": "Use it to verify X-Stockroom-Signature"})


class WebhookDeliverySchema(Schema):
    id = fields.Integer(dump_only=True)
    event_id = fields.String(dump_only=True)
    event_type = fields.String(dump_only=True)
    target_url = fields.String(dump_only=True)
    status = fields.String(dump_only=True, metadata={"description": "pending, delivered or dead"})
    attempts = fields.Integer(dump_only=True)
    last_error = fields.String(dump_only=True, allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    delivered_at = fields.DateTime(dump_only=True, allow_none=True)
