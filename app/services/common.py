"""Small helpers shared by the services."""

from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError
from app.extensions import db


def commit_or_conflict(detail: str) -> None:
    """Save, turning a broken unique rule (e.g. two requests at the same moment) into a 409."""
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ConflictError(detail) from error
