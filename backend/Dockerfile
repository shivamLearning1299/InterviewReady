# =============================================================================
# InterviewReady API
# =============================================================================
# Multi-stage build: the wheel layer compiles dependencies once, and the runtime
# layer carries only what the app needs — no compilers, no test dependencies.
#
# Python 3.12 is pinned deliberately. The dependency set (asyncpg / SQLAlchemy /
# FastAPI as resolved in requirements.txt) is not yet validated on 3.13+, so the
# image matches the version the test suite runs against.
# =============================================================================

# ------------------------------------------------------------------- build stage
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build toolchain for any dependency that ships as an sdist. Kept in the builder stage
# only, so the runtime image stays small.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy just the requirement manifests first so the dependency layer is cached and is
# only rebuilt when the dependencies themselves change.
COPY requirements.txt ./

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# ----------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq is needed at runtime by asyncpg's linked client libraries; curl is used by the
# container health check.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user. The app never needs to write to its own source tree.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser . .

USER appuser

# Documentation only. The real port is $PORT at runtime (Render injects it; the default
# below matches this EXPOSE for a plain `docker run`).
EXPOSE 8000

# Reports unhealthy until the database and auth configuration are both usable, so the
# platform does not route traffic to an instance that cannot serve requests.
# Probes the port the server is actually listening on, so the check still works when
# $PORT differs from the default.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health/ready" || exit 1

# Migrations run first so a release either brings the schema up to date or fails loudly.
# Honour $PORT so a plain `docker run` behaves the same as Render, which overrides this
# with its own command. Hardcoding 8000 here made local runs and production diverge, which
# is exactly the kind of difference that only shows up after a deploy.
#
# `--workers` is left to the platform: Render's blueprint sets 2 explicitly, and a single
# worker is the safe default when the port and CPU count are unknown.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
