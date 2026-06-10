# syntax=docker/dockerfile:1
#
# Container image for the ANNCSU Workflow API, built entirely on uv:
#   - `uv sync --frozen` installs the locked dependencies into /app/.venv
#   - `uv run fastapi run` serves app.main:app in production mode
#
# Build:  docker build -t anncsu-workflow-api .
# Run:    docker run -p 8000:8000 --env-file .env anncsu-workflow-api

# Base image pinned by digest (supply-chain hardening); tag kept for readability.
FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

# Apply Debian security updates on top of the pinned base so Trivy's "fixable
# HIGH/CRITICAL" gate stays green as patches land (e.g. OpenSSL CVE-2026-45447).
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# uv binary from the official distroless image, pinned by digest.
COPY --from=ghcr.io/astral-sh/uv:0.9.7@sha256:ba4857bf2a068e9bc0e64eed8563b065908a4cd6bfb66b531a9c424c8e25e142 /uv /uvx /bin/

WORKDIR /app

# Compile bytecode and copy (instead of hardlink) packages into the image layer.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# 1) Install dependencies first (cached unless the lock changes), without the
#    project itself, so source edits don't bust the dependency layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) Copy the app and install the project into the venv.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# `fastapi run` defaults to production mode (no reload) on 0.0.0.0:8000.
CMD ["uv", "run", "--no-sync", "fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
