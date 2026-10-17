"""backfill lowercase user emails

Data migration: lowercases the emails of users that already exist, then adds a
CHECK rule so every future email must be lowercase too.

Revision ID: aed0fa2909db
Revises: fbceed2e8e1b
Create Date: 2026-10-14 10:46:16.024153

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aed0fa2909db"
down_revision: str | Sequence[str] | None = "fbceed2e8e1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A small stand-in for the users table. Migrations must not import the app's models,
# because the models keep changing while this file must keep working as written.
users = sa.table("users", sa.column("id", sa.Integer), sa.column("email", sa.String))
normalized_email = sa.func.lower(sa.func.trim(users.c.email))


def upgrade() -> None:
    """Lowercase existing emails, then forbid mixed-case emails."""
    # Stop with a clear message if two users would end up with the same email
    clashes = (
        op.get_bind()
        .execute(sa.select(normalized_email).group_by(normalized_email).having(sa.func.count() > 1))
        .scalars()
        .all()
    )
    if clashes:
        raise RuntimeError(f"Lowercasing would create duplicate emails: {', '.join(clashes)}")

    op.execute(
        users.update().where(users.c.email != normalized_email).values(email=normalized_email)
    )
    op.create_check_constraint(op.f("ck_users_email_lowercase"), "users", "email = lower(email)")


def downgrade() -> None:
    """Remove the rule. The emails stay lowercase: their original capitals are not recorded."""
    op.drop_constraint(op.f("ck_users_email_lowercase"), "users", type_="check")
