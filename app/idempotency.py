"""Idempotency-Key support for POST endpoints.

A client sends `Idempotency-Key: <any unique string>` with a POST. If the same request
arrives again with the same key (for example a retry after a timeout), we send back the
first response instead of doing the work twice: no duplicate orders, no double stock moves.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

from flask import Response, jsonify, make_response, request
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.auth import current_tenant_id
from app.errors import ApiError, ConflictError
from app.extensions import db
from app.models import IdempotencyKey

HEADER = "Idempotency-Key"
KEY_LIFETIME = timedelta(hours=24)

# Documents the header on /docs: use as @blp.doc(**ACCEPTS_IDEMPOTENCY_KEY)
ACCEPTS_IDEMPOTENCY_KEY: dict[str, Any] = {
    "parameters": [
        {
            "in": "header",
            "name": HEADER,
            "required": False,
            "schema": {"type": "string", "maxLength": 255},
            "description": "Any unique string. Repeating the request with the same key "
            "returns the first response instead of doing the work again.",
        }
    ]
}


class IdempotencyKeyReusedError(ApiError):
    status = 422
    title = "Idempotency-Key reused"
    problem_type = "/problems/idempotency-key-reused"


class InvalidIdempotencyKeyError(ApiError):
    status = 400
    title = "Invalid Idempotency-Key"


def _fingerprint() -> str:
    """SHA-256 of the request, to notice a key being reused for a different request."""
    digest = hashlib.sha256()
    for part in (request.method.encode(), request.path.encode(), request.get_data()):
        digest.update(part)
        digest.update(b"\n")
    return digest.hexdigest()


def _find(tenant_id: int, key: str) -> IdempotencyKey | None:
    record = db.session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key
        )
    )
    if record is not None and record.created_at < datetime.now(UTC) - KEY_LIFETIME:
        _release(tenant_id, key)  # expired: treat the key as new
        return None
    return record


def _claim(tenant_id: int, key: str, fingerprint: str) -> None:
    """Save the key before doing the work. The unique rule lets only one request win."""
    db.session.add(IdempotencyKey(tenant_id=tenant_id, key=key, request_hash=fingerprint))
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise _still_running() from error


def _release(tenant_id: int, key: str) -> None:
    """Forget the key (the request failed), so the client can retry with it."""
    db.session.rollback()  # throw away any half-done work first
    db.session.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key
        )
    )
    db.session.commit()


def _remember(tenant_id: int, key: str, response: Response) -> None:
    db.session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key)
        .values(response_status=response.status_code, response_body=response.get_json(silent=True))
    )
    db.session.commit()


def _replay(record: IdempotencyKey, fingerprint: str) -> Response:
    if record.request_hash != fingerprint:
        raise IdempotencyKeyReusedError(
            "This Idempotency-Key was already used for a different request. Use a new key."
        )
    if record.response_status is None:
        raise _still_running()

    response = jsonify(record.response_body)
    response.status_code = record.response_status
    response.headers["Idempotent-Replayed"] = "true"
    return response


def _still_running() -> ConflictError:
    return ConflictError(
        "A request with this Idempotency-Key is still being processed. Try again shortly."
    )


def idempotent[**P](view: Callable[P, Any]) -> Callable[P, Any]:
    """Make a POST endpoint safe to retry with an Idempotency-Key header.

    Put it below @auth_required (it needs the tenant) and above @blp.arguments.
    Only completed requests are remembered. Errors arrive as exceptions (e.g. 409 not enough
    stock); then the key is released, because a failed request changed nothing and may be
    retried with the same key.
    """

    @wraps(view)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        key = request.headers.get(HEADER)
        if not key:
            return view(*args, **kwargs)
        if len(key) > 255:
            raise InvalidIdempotencyKeyError(f"{HEADER} must be at most 255 characters.")

        tenant_id = current_tenant_id()
        fingerprint = _fingerprint()
        record = _find(tenant_id, key)
        if record is not None:
            return _replay(record, fingerprint)

        _claim(tenant_id, key, fingerprint)
        try:
            response = make_response(view(*args, **kwargs))
        except Exception:
            _release(tenant_id, key)
            raise
        _remember(tenant_id, key, response)
        return response

    return wrapper
