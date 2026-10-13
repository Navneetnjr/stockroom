from flask import Blueprint

health_bp = Blueprint("health", __name__)


@health_bp.get("/healthz")
def healthz() -> tuple[dict[str, str], int]:
    """Liveness check: answers as long as the app process is running."""
    return {"status": "ok"}, 200
