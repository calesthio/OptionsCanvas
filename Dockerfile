# syntax=docker/dockerfile:1.6
# ============================================================================
# OptionsCanvas — production container
#
# Single-stage build using python:3.11-slim. The app is pure Python +
# vanilla-JS frontend served by Flask, so no Node build step is needed.
# Config and SQLite state are expected to be mounted as volumes
# (see docker-compose.yml) so user data survives container rebuilds.
# ============================================================================
FROM python:3.11-slim

# OS-level deps. curl is used by the in-container healthcheck only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so layer caches when only app code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# App source (note: .dockerignore filters out venvs, caches, secrets).
COPY . .

# Marker so the venv-based launchers don't try to bootstrap inside the
# container — pip install already ran in the image build.
RUN mkdir -p /app/.venv \
    && touch /app/.venv/.deps_installed

# Run as non-root.
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 5001

# Health: /api/health works in both setup-mode and trading-mode.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5001/api/health || exit 1

# The launcher auto-opens a browser; suppress that in the container
# (BROWSER=none is the conventional override) — we'll bind 5001 and
# the user opens it from the host.
ENV BROWSER=none \
    PYTHONUNBUFFERED=1

CMD ["python", "assisted_trading/run_platform.py"]
