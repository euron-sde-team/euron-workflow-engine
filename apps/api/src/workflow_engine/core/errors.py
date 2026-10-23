"""Typed application errors and the one error envelope every response uses.

    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": ...}}

Services raise these; routes never build error responses by hand. Unexpected exceptions
become a 500 with no internal detail, and the full traceback goes to the log under the
same request id.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from workflow_engine.core.context import get_request_id
from workflow_engine.core.logging import get_logger

log = get_logger("wfe.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers or {}
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Sign in to continue."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do that."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "That conflicts with existing data."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "The upload is larger than this deployment allows."


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"
    message = "That file type is not supported."


class UnprocessableError(AppError):
    status_code = 422
    code = "validation_failed"
    message = "Some fields are invalid."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Try again shortly."


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
    message = "An upstream service did not respond as expected."


class MethodNotAllowedError(AppError):
    status_code = 405
    code = "method_not_allowed"
    message = "That method is not allowed here."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A dependency is unavailable."


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details is not None:
        error["details"] = details
    return {"error": error}


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, exc.details),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", ())), "message": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_failed", "Some fields are invalid.", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            error_body(code, message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            error_body("internal_error", "Something went wrong on our side."), status_code=500
        )
