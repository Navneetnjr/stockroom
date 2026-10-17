"""Logs you can search: JSON lines with a request id, the caller's tenant and user, request
latency, and a warning for every slow database query."""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from flask import Flask, Response, g, request
from sqlalchemy import Connection, event
from sqlalchemy.engine import Engine

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller's request id only if it is short and plain, so logs can't be tampered with
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_HANDLER_NAME = "stockroom-json"

# Who and what the current request is about. Context variables keep requests that run at the
# same time (in different threads) from mixing up each other's values.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[int | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)

_request_log = logging.getLogger("stockroom.request")
_sql_log = logging.getLogger("stockroom.sql")
_slow_query = {"threshold_ms": 200.0}

# Attributes every log record has; anything else was added on purpose and goes into the JSON
_STANDARD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Writes each log record as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRIBUTES and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class RequestContextFilter(logging.Filter):
    """Adds the current request id, tenant and user to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name, var in (
            ("request_id", request_id_var),
            ("tenant_id", tenant_id_var),
            ("user_id", user_id_var),
        ):
            if not hasattr(record, name):
                setattr(record, name, var.get())
        return True


def configure_logging(level: str) -> None:
    """Send all logs to stdout as JSON (cloud platforms collect stdout)."""
    root = logging.getLogger()
    for handler in list(root.handlers):  # running twice (e.g. in tests) must not log twice
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)
    root.setLevel(level)
    # We log every request ourselves, so silence the dev server's own access lines
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def bind_identity(tenant_id: int, user_id: int) -> None:
    """Record who is calling, once their login token has been checked."""
    tenant_id_var.set(tenant_id)
    user_id_var.set(user_id)


def current_request_id() -> str | None:
    """The id of the current request, to hand on to background jobs and webhooks."""
    return request_id_var.get()


def bind_request_id(request_id: str | None) -> None:
    """Continue the request id inside a background job (or start a new one)."""
    request_id_var.set(request_id or uuid.uuid4().hex)


def init_request_logging(app: Flask) -> None:
    """Give every request an id and write one log line when it finishes."""

    @app.before_request
    def start_request() -> None:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id_var.set(incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex)
        tenant_id_var.set(None)
        user_id_var.set(None)
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request(response: Response) -> Response:
        started = g.get("request_started", time.perf_counter())
        response.headers[REQUEST_ID_HEADER] = request_id_var.get() or ""
        _request_log.log(
            logging.ERROR if response.status_code >= 500 else logging.INFO,
            "request completed",
            extra={
                "request_id": request_id_var.get(),
                "tenant_id": tenant_id_var.get(),
                "user_id": user_id_var.get(),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response


def enable_slow_query_logging(threshold_ms: float) -> None:
    """Log every database query that takes at least `threshold_ms`, with its SQL."""
    _slow_query["threshold_ms"] = threshold_ms
    if not event.contains(Engine, "before_cursor_execute", _start_query_timer):
        event.listen(Engine, "before_cursor_execute", _start_query_timer)
        event.listen(Engine, "after_cursor_execute", _log_if_slow)


def _start_query_timer(
    conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
) -> None:
    conn.info.setdefault("query_started", []).append(time.perf_counter())


def _log_if_slow(
    conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
) -> None:
    duration_ms = (time.perf_counter() - conn.info["query_started"].pop()) * 1000
    if duration_ms >= _slow_query["threshold_ms"]:
        _sql_log.warning(
            "slow query",
            extra={
                "duration_ms": round(duration_ms, 1),
                "sql": statement,
                "params": redact(parameters),
            },
        )


def redact(parameters: Any) -> Any:
    """Hide password values before query parameters are written to the logs."""
    if isinstance(parameters, dict):
        return {
            key: "***" if "password" in str(key).lower() else value
            for key, value in parameters.items()
        }
    if isinstance(parameters, list | tuple) and parameters and isinstance(parameters[0], dict):
        return [redact(item) for item in parameters]
    return parameters
