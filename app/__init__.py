from flask import Flask

from app.api.health import health_bp


def create_app() -> Flask:
    """Build and configure the Flask application."""
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    return app
