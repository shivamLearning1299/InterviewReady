"""Request-scoped middleware: correlation ids, structured access logs, timing."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_context, clear_request_context, get_logger

logger = get_logger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"

#: Never log these request bodies/paths verbatim — they can carry credentials.
_SENSITIVE_PATH_FRAGMENTS = ("/auth", "/token", "/password")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, then log method/path/status/duration for every request.

    The log record intentionally excludes the authorization header and request bodies, so
    JWTs and user code never reach the log stream.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and len(incoming) <= 64 else str(uuid.uuid4())

        request.state.request_id = request_id
        clear_request_context()
        bind_request_context(request_id=request_id)

        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": duration_ms,
                },
            )
            clear_request_context()
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id

        log_extra = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "user_id": getattr(request.state, "user_id", None),
        }

        # Query strings can contain filters with user content; log the key names only.
        if request.url.query:
            log_extra["query_keys"] = sorted(
                {pair.split("=")[0] for pair in request.url.query.split("&") if pair}
            )

        if any(fragment in request.url.path for fragment in _SENSITIVE_PATH_FRAGMENTS):
            log_extra["path"] = "[redacted]"

        level = 20 if response.status_code < 500 else 40
        logger.log(level, "request", extra=log_extra)

        clear_request_context()
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Conservative default security headers for an API."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
