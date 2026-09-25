"""Typed application exceptions and the unified error envelope.

Every failure surfaced to a client uses::

    {"error": {"code": "...", "message": "...", "details": ...}}

Routes and services raise the semantic exceptions below; a single set of handlers in
``app.api.error_handlers`` converts them (and framework-level errors) into that shape
with the appropriate HTTP status code.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class AppError(Exception):
    """Base class for all deliberate, client-visible application errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    message = "The request could not be processed."


class ValidationError(AppError):
    # 422 literal rather than Starlette's constant: the constant was renamed
    # (HTTP_422_UNPROCESSABLE_ENTITY -> HTTP_422_UNPROCESSABLE_CONTENT) and importing it
    # emits a deprecation warning on newer Starlette versions.
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Request validation failed."


class UnauthenticatedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"
    message = "Authentication credentials were missing or invalid."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The resource was modified by another request."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Too many requests. Please slow down."


class ExternalServiceError(AppError):
    """An upstream dependency (e.g. the AI provider) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "UPSTREAM_ERROR"
    message = "An upstream service is unavailable."


# ---------------------------------------------------------------- domain specifics
class ProblemNotFoundError(NotFoundError):
    code = "PROBLEM_NOT_FOUND"
    message = "DSA problem not found"


class TopicNotFoundError(NotFoundError):
    code = "TOPIC_NOT_FOUND"
    message = "Topic not found"


class AttemptNotFoundError(NotFoundError):
    code = "ATTEMPT_NOT_FOUND"
    message = "Problem attempt not found"


class SnippetNotFoundError(NotFoundError):
    code = "SNIPPET_NOT_FOUND"
    message = "Code snippet not found"


class RevisionNotFoundError(NotFoundError):
    code = "REVISION_NOT_FOUND"
    message = "Revision not found"


class StudySessionNotFoundError(NotFoundError):
    code = "STUDY_SESSION_NOT_FOUND"
    message = "Study session not found"


class ConversationNotFoundError(NotFoundError):
    code = "CONVERSATION_NOT_FOUND"
    message = "AI conversation not found"


class DailyPlanNotFoundError(NotFoundError):
    code = "DAILY_PLAN_NOT_FOUND"
    message = "No daily plan exists for that date"


class AlreadyCompletedError(ConflictError):
    code = "ALREADY_COMPLETED"
    message = "This item has already been completed"


class StudySessionConflictError(ConflictError):
    code = "STUDY_SESSION_CONFLICT"
    message = "A study session is already running for this user"


class SyncConflictError(ConflictError):
    """Raised for a per-mutation optimistic-concurrency conflict.

    The sync endpoint reports conflicts inside a 200 response, so this class is used
    for the internal control flow and for surfacing a conflict on the non-sync routes.
    """

    code = "VERSION_CONFLICT"
    message = "The record was modified on the server after your last sync"


class UnsupportedOperationError(BadRequestError):
    code = "UNSUPPORTED_OPERATION"
    message = "The requested operation is not supported"


class AIProviderError(ExternalServiceError):
    code = "AI_PROVIDER_ERROR"
    message = "The AI provider could not be reached"


class AIConfigurationError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "AI_NOT_CONFIGURED"
    message = "The AI tutor is not configured on this server"
