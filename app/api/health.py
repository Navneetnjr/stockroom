from flask_smorest import Blueprint
from marshmallow import Schema, fields
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

blp = Blueprint("health", __name__, description="Is the service alive and ready to work?")


class HealthSchema(Schema):
    status = fields.String(metadata={"example": "ok"})


class ReadinessSchema(Schema):
    status = fields.String(metadata={"example": "ok"})
    database = fields.String(metadata={"example": "up"})


@blp.route("/healthz")
@blp.response(200, HealthSchema)
def healthz() -> dict[str, str]:
    """Liveness check

    Answers as long as the app process is running.
    """
    return {"status": "ok"}


@blp.route("/readyz")
@blp.response(200, ReadinessSchema)
@blp.alt_response(503, schema=ReadinessSchema, description="The database cannot be reached")
def readyz() -> dict[str, str] | tuple[dict[str, str], int]:
    """Readiness check

    Answers ok only if the database can be reached.
    """
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return {"status": "unavailable", "database": "down"}, 503
    return {"status": "ok", "database": "up"}
