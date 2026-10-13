from flask import Blueprint
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.get("/healthz")
def healthz() -> tuple[dict[str, str], int]:
    """Liveness check: answers as long as the app process is running."""
    return {"status": "ok"}, 200


@health_bp.get("/readyz")
def readyz() -> tuple[dict[str, str], int]:
    """Readiness check: answers ok only if the database can be reached."""
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return {"status": "unavailable", "database": "down"}, 503
    return {"status": "ok", "database": "up"}, 200
