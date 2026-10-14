"""Checks the data migration really fixes rows that existed before it ran."""

from alembic import command
from flask import Flask
from sqlalchemy import text

from app.extensions import db
from tests.helpers import alembic_config

BEFORE_EMAIL_BACKFILL = "fbceed2e8e1b"


def test_email_backfill_lowercases_existing_users(app: Flask) -> None:
    config = alembic_config()
    command.downgrade(config, BEFORE_EMAIL_BACKFILL)
    try:
        # An "old" user saved before emails were normalised (raw SQL, as old code might have)
        with app.app_context():
            tenant_id = db.session.execute(
                text("INSERT INTO tenants (name) VALUES ('Old Shop') RETURNING id")
            ).scalar_one()
            db.session.execute(
                text(
                    "INSERT INTO users (tenant_id, email, password_hash, role) "
                    "VALUES (:tenant_id, ' Old.Owner@Shop.TEST ', 'x', 'admin')"
                ),
                {"tenant_id": tenant_id},
            )
            db.session.commit()
    finally:
        command.upgrade(config, "head")

    with app.app_context():
        email = db.session.scalar(text("SELECT email FROM users"))
    assert email == "old.owner@shop.test"
