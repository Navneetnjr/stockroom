import json
import logging
import sys

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app.extensions import db
from app.observability import (
    JsonFormatter,
    RequestContextFilter,
    configure_logging,
    redact,
    request_id_var,
)
from tests.helpers import auth_header, register_shop

# --- Request ids ----------------------------------------------------------------------------


def test_every_response_gets_a_request_id(client: FlaskClient) -> None:
    first = client.get("/healthz").headers["X-Request-ID"]
    second = client.get("/healthz").headers["X-Request-ID"]

    assert len(first) == 32  # a random uuid4 in hex
    assert first != second


def test_callers_request_id_is_kept(client: FlaskClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "checkout-flow-42"})

    assert response.headers["X-Request-ID"] == "checkout-flow-42"


def test_unsafe_request_id_is_replaced(client: FlaskClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "fake\tlog line"})

    assert response.headers["X-Request-ID"] != "fake\tlog line"
    assert len(response.headers["X-Request-ID"]) == 32


# --- One log line per request ---------------------------------------------------------------


def test_request_log_line_says_who_what_and_how_long(
    client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = register_shop(client)
    caplog.set_level(logging.INFO, logger="stockroom.request")

    response = client.get("/auth/me", headers=auth_header(token))

    me = response.get_json()
    record = next(r for r in caplog.records if getattr(r, "path", None) == "/auth/me")
    assert record.getMessage() == "request completed"
    assert (
        record.__dict__
        | {
            "request_id": response.headers["X-Request-ID"],
            "tenant_id": me["tenant_id"],
            "user_id": me["id"],
            "method": "GET",
            "status": 200,
        }
        == record.__dict__
    )
    assert record.__dict__["latency_ms"] >= 0


def test_anonymous_request_is_logged_without_tenant(
    client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="stockroom.request")

    client.get("/healthz")

    record = next(r for r in caplog.records if getattr(r, "path", None) == "/healthz")
    assert record.__dict__["tenant_id"] is None
    assert record.__dict__["user_id"] is None


# --- Slow query log -------------------------------------------------------------------------


def test_slow_query_is_logged_with_its_sql(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="stockroom.sql")

    with app.app_context():
        db.session.execute(text("SELECT pg_sleep(0.25)"))  # 250 ms: over the 200 ms limit

    record = next(r for r in caplog.records if r.getMessage() == "slow query")
    assert "pg_sleep" in record.__dict__["sql"]
    assert record.__dict__["duration_ms"] >= 200


def test_fast_query_is_not_logged(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="stockroom.sql")

    with app.app_context():
        db.session.execute(text("SELECT 1"))

    assert not [r for r in caplog.records if r.getMessage() == "slow query"]


def test_passwords_are_hidden_in_logged_parameters() -> None:
    single = {"email": "a@b.test", "password_hash": "scrypt:secret"}
    many = [single, {"email": "c@d.test", "password_hash": "scrypt:other"}]

    assert redact(single) == {"email": "a@b.test", "password_hash": "***"}
    assert redact(many) == [
        {"email": "a@b.test", "password_hash": "***"},
        {"email": "c@d.test", "password_hash": "***"},
    ]
    assert redact((1, 2)) == (1, 2)  # positional parameters have no names to check


# --- The JSON format itself -----------------------------------------------------------------


def test_log_record_becomes_one_json_line() -> None:
    record = logging.makeLogRecord(
        {"name": "stockroom.test", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    record.status = 201

    line = JsonFormatter().format(record)

    entry = json.loads(line)
    assert "\n" not in line
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["status"] == 201
    assert entry["timestamp"].endswith("+00:00")


def test_errors_include_the_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})

    entry = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in entry["exception"]


def test_context_filter_adds_the_current_request_id() -> None:
    token = request_id_var.set("req-1")
    try:
        record = logging.makeLogRecord({"msg": "inside a request"})
        RequestContextFilter().filter(record)
    finally:
        request_id_var.reset(token)

    assert record.__dict__["request_id"] == "req-1"


def test_configuring_logging_twice_does_not_duplicate_lines() -> None:
    configure_logging("INFO")
    configure_logging("INFO")

    ours = [h for h in logging.getLogger().handlers if h.get_name() == "stockroom-json"]
    assert len(ours) == 1
