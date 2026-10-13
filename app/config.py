import os

from dotenv import load_dotenv

# Copy values from a local .env file into environment variables (skipped if there is no .env)
load_dotenv()


class Config:
    """App settings, read from environment variables."""

    SQLALCHEMY_DATABASE_URI: str | None = os.environ.get("DATABASE_URL")
    # Check a pooled connection is still alive before using it
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, bool] = {"pool_pre_ping": True}
