"""Error responses in the RFC 9457 "problem details" format.

Every error the API returns has the same shape, for example:

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "The requested URL was not found on the server.", "instance": "/nope"}
"""

from typing import Any

from flask import Flask, Response, current_app, jsonify, request
from flask_smorest import Api
from marshmallow import Schema, fields
from werkzeug.exceptions import HTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemSchema(Schema):
    """The shape of every error response (shown on the /docs page)."""

    type = fields.String(metadata={"example": "about:blank"})
    title = fields.String(metadata={"example": "Not Found"})
    status = fields.Integer(metadata={"example": 404})
    detail = fields.String(metadata={"example": "The requested URL was not found on the server."})
    instance = fields.String(metadata={"example": "/products/42"})
    errors = fields.Dict(metadata={"description": "Field-by-field messages (validation errors)"})


class ApiError(Exception):
    """Raise a subclass of this anywhere in the app to send a problem response."""

    status = 400
    title = "Bad Request"
    problem_type = "about:blank"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnauthorizedError(ApiError):
    status = 401
    title = "Unauthorized"


class ForbiddenError(ApiError):
    status = 403
    title = "Forbidden"


class NotFoundError(ApiError):
    status = 404
    title = "Not Found"


class ConflictError(ApiError):
    status = 409
    title = "Conflict"


def problem_response(
    status: int,
    title: str,
    detail: str | None = None,
    problem_type: str = "about:blank",
    **extra: Any,
) -> Response:
    """Build a JSON problem response."""
    body: dict[str, Any] = {"type": problem_type, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body["instance"] = request.path
    body.update(extra)

    response = jsonify(body)
    response.status_code = status
    response.content_type = PROBLEM_CONTENT_TYPE
    return response


class StockroomApi(Api):
    """flask-smorest's Api, changed so HTTP errors are documented and sent as problems."""

    ERROR_SCHEMA = ProblemSchema

    def handle_http_exception(self, error: HTTPException) -> Response:
        """Turn errors like 404, 405 and 422 into problem responses."""
        extra: dict[str, Any] = {}
        data = getattr(error, "data", None) or {}
        # On 422 errors, webargs puts the field-by-field validation messages here
        if "messages" in data:
            extra["errors"] = data["messages"]

        response = problem_response(error.code or 500, error.name, error.description, **extra)
        # Keep extra headers the error carries, e.g. "Allow" on 405 Method Not Allowed
        for name, value in error.get_headers():
            if name.lower() != "content-type":
                response.headers[name] = value
        for name, value in (data.get("headers") or {}).items():
            response.headers[name] = value
        return response


def register_error_handlers(app: Flask) -> None:
    """Send our own errors, and any crash, as problem responses."""

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError) -> Response:
        return problem_response(error.status, error.title, error.detail, error.problem_type)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> Response:
        # Log the full error for us, but never show internal details to the caller
        current_app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return problem_response(500, "Internal Server Error", "Something went wrong on our side.")
