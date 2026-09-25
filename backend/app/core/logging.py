"""Structured application logging with request correlation.

Emits either JSON (production, log aggregators) or a human-readable coloured line
(development). A request-scoped ``request_id`` and ``user_id`` are propagated via
contextvars so every log line raised while handling a request is correlated without
threading extra arguments through service layers.

Secret-bearing values (JWTs, API keys, passwords) are never logged; see
``app.core.logging.SENSITIVE_KEYS`` for the redaction list used by the request logger.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "apikey",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "jwt",
        "code",
    }
)

# Attributes LogRecord always carries; anything else came from `extra=`.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return ``value`` with sensitive payloads masked."""
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return "***redacted***"
    if isinstance(value, dict):
        return {k: redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class RequestContextFilter(logging.Filter):
    """Injects the ambient request id / user id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_ctx.get()
        if not getattr(record, "user_id", None):
            record.user_id = user_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal, dependency-free JSON formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = redact(value, key=key)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = [
            f"{key}={value!r}"
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_") and key not in {"request_id", "user_id"}
        ]
        request_id = getattr(record, "request_id", None)
        prefix = f"[{request_id[:8]}] " if request_id else ""
        suffix = f" {' '.join(extras)}" if extras else ""
        return f"{prefix}{base}{suffix}"


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = True,
    force: bool = False,
) -> None:
    """Install a single stdout handler on the root logger.

    Idempotent: repeated calls (e.g. in tests) will not stack handlers unless
    ``force`` is set.
    """
    root = logging.getLogger()
    if root.handlers and not force:
        root.setLevel(level)
        return

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else ConsoleFormatter("%(asctime)s %(levelname)-8s %(name)s %(message)s", "%H:%M:%S")
    )

    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn/unwanted noise: keep access logs, quiet the chatty internals.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def bind_request_context(request_id: str | None = None, user_id: str | None = None) -> None:
    """Attach a request/user id to the current context."""
    if request_id is not None:
        request_id_ctx.set(request_id)
    if user_id is not None:
        user_id_ctx.set(user_id)


def clear_request_context() -> None:
    request_id_ctx.set(None)
    user_id_ctx.set(None)
