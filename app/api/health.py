from flask_smorest import Blueprint
from marshmallow import Schema, fields
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cache import redis_status
from app.extensions import db

blp = Blueprint("health", __name__, description="Is the service alive and ready to work?")


class HealthSchema(Schema):
    status = fields.String(metadata={"example": "ok"})


class ReadinessSchema(Schema):
    status = fields.String(metadata={"example": "ok"})
    database = fields.String(metadata={"example": "up"})
    redis = fields.String(metadata={"example": "up", "description": "up, down or not configured"})


@blp.route("/healthz")
@blp.response(200, HealthSchema)
def healthz() -> dict[str, str]:
    """Liveness check

    Answers as long as the app process is running.
    """
    return {"status": "ok"}


@blp.route("/readyz")
@blp.response(200, ReadinessSchema)
@blp.alt_response(503, schema=ReadinessSchema, description="The database or Redis is down")
def readyz() -> dict[str, str] | tuple[dict[str, str], int]:
    """Readiness check

    Answers ok only if the database can be reached, and Redis too when it is configured.
    """
    try:
        db.session.execute(text("SELECT 1"))
        database = "up"
    except SQLAlchemyError:
        database = "down"
    redis = redis_status()

    if database == "down" or redis == "down":
        return {"status": "unavailable", "database": database, "redis": redis}, 503
    return {"status": "ok", "database": database, "redis": redis}
