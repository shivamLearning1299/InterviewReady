"""Centralised exception handlers producing the unified error envelope.

Every response that is not a success uses::

    {"error": {"code": "...", "message": "...", "details": ...}}

Framework-level failures are mapped too (validation, 404 from Starlette, unhandled
exceptions) so clients only ever parse one error shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Map bare HTTP status codes to a stable machine-readable error code.
STATUS_CODE_MAP: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}

STATUS_MESSAGE_MAP: dict[int, str] = {
    401: "Authentication credentials were missing or invalid.",
    403: "You do not have permission to perform this action.",
    404: "The requested resource was not found.",
    405: "That HTTP method is not allowed for this endpoint.",
    429: "Too many requests. Please slow down.",
    500: "An unexpected error occurred.",
    503: "The service is temporarily unavailable.",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the application."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if exc.status_code == 401
            else None
        )
        # 5xx are our fault and worth a full traceback; 4xx are expected client mistakes.
        if exc.status_code >= 500:
            logger.error(
                "Application error",
                extra={"code": exc.code, "status": exc.status_code},
                exc_info=exc,
            )
        else:
            logger.info(
                "Request rejected",
                extra={"code": exc.code, "status": exc.status_code, "reason": exc.message},
            )
        return error_response(
            exc.status_code, exc.code, exc.message, exc.details, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten pydantic's error list into something a client can render per field.
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                "message": error.get("msg"),
                "type": error.get("type"),
            }
            for error in exc.errors()
        ]
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Request validation failed.",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODE_MAP.get(exc.status_code, "HTTP_ERROR")
        message = STATUS_MESSAGE_MAP.get(exc.status_code) or str(exc.detail)
        headers = getattr(exc, "headers", None)
        return error_response(exc.status_code, code, message, None, headers=headers)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        """Translate the database constraint names we rely on into useful API errors.

        These constraints are load-bearing for correctness (daily-plan uniqueness, sync
        mutation idempotency), so their violations get a precise code rather than a
        generic 409.
        """
        # Interpolate the driver message into the log text rather than passing it as an
        # `extra` field: the console formatter only renders the configured extras, so a
        # constraint violation would otherwise be logged as a bare "Integrity error" with
        # no indication of which constraint failed.
        detail = str(getattr(exc, "orig", exc))
        logger.warning("Integrity error: %s", detail[:400])

        mappings: tuple[tuple[str, str, str], ...] = (
            (
                "uq_daily_plans_user_id_plan_date",
                "DAILY_PLAN_EXISTS",
                "A daily plan already exists for that date.",
            ),
            (
                "uq_sync_mutations_user_id_mutation_id",
                "DUPLICATE_MUTATION",
                "That mutation has already been applied.",
            ),
            (
                "uq_user_problem_progress_user_id_problem_id",
                "PROGRESS_EXISTS",
                "Progress for that problem already exists.",
            ),
            (
                "uq_problem_notes_user_id_problem_id",
                "NOTES_EXIST",
                "Notes for that problem already exist.",
            ),
            (
                "uq_study_sessions_user_id_device_identifier",
                "DEVICE_EXISTS",
                "That device is already registered.",
            ),
            (
                "uq_study_sessions_one_active_per_user",
                "STUDY_SESSION_CONFLICT",
                "A study session is already running.",
            ),
        )

        for constraint, code, message in mappings:
            if constraint in detail:
                return error_response(409, code, message)

        # A foreign-key violation means the referenced catalog row does not exist.
        if "foreign key" in detail.lower():
            return error_response(
                404,
                "RELATED_RESOURCE_NOT_FOUND",
                "A referenced resource does not exist.",
            )

        if "unique" in detail.lower() or "duplicate" in detail.lower():
            return error_response(
                409, "CONFLICT", "That record already exists or conflicts with an existing one."
            )

        if "check constraint" in detail.lower():
            return error_response(422, "VALIDATION_ERROR", "A submitted value failed validation.")

        return error_response(409, "CONFLICT", "The request conflicts with the current state.")

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database_unavailable(_: Request, exc: Exception) -> JSONResponse:
        # `@app.exception_handler` stacks: both OperationalError and InterfaceError route
        # here, so a dropped connection or a pooler hiccup yields a retryable 503 rather
        # than an opaque 500.
        logger.error("Database unavailable", exc_info=exc)
        return error_response(
            503,
            "DATABASE_UNAVAILABLE",
            "The database is temporarily unavailable. Please retry.",
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database error", exc_info=exc)
        return error_response(500, "DATABASE_ERROR", "A database error occurred.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        return error_response(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )
