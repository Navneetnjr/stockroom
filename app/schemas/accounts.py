from marshmallow import Schema, fields, validate

from app.models import UserRole

PASSWORD_RULES = validate.Length(min=8, max=128)


class TenantSchema(Schema):
    id = fields.Integer(dump_only=True)
    name = fields.String(dump_only=True)


class UserSchema(Schema):
    id = fields.Integer(dump_only=True)
    email = fields.Email(dump_only=True)
    role = fields.String(dump_only=True)
    tenant_id = fields.Integer(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class RegisterSchema(Schema):
    shop_name = fields.String(required=True, validate=validate.Length(min=1, max=200))
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True, validate=PASSWORD_RULES)


class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True)


class TokenSchema(Schema):
    access_token = fields.String(metadata={"description": "Paste this into the Authorize button"})
    token_type = fields.String(metadata={"example": "Bearer"})
    user = fields.Nested(UserSchema)
    tenant = fields.Nested(TenantSchema)


class CreateUserSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True, validate=PASSWORD_RULES)
    role = fields.String(
        load_default=UserRole.STAFF.value,
        validate=validate.OneOf([role.value for role in UserRole]),
    )
