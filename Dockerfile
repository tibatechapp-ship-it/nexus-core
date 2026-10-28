# syntax=docker/dockerfile:1
#
# nexus-core — production image (multi-stage)
#
# Stage 1 resolves and compiles every dependency into wheels; stage 2 is a slim
# runtime with no compiler, no build headers and no pip cache. The server is the
# documented workbench app (`main.py`), so the container starts exactly what
# docs/openapi.yaml describes.
#
#   docker build -t nexus-core:local .
#   docker run --rm -p 8000:8000 nexus-core:local
#
# The container binds 0.0.0.0 (a container that binds loopback is unreachable);
# exposure is controlled by compose's published port / the platform's router.

ARG PYTHON_VERSION=3.12

# ───────────────────────────── build stage ─────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# libpq-dev: only needed while wheels that link libpq are built (psycopg[binary]
# ships its own, but other deps may compile). Nothing from this stage ships.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-docker.txt .
RUN pip wheel --wheel-dir /wheels -r requirements-docker.txt

# ──────────────────────────── runtime stage ────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_PORT=8000

# A fixed, unprivileged uid/gid keeps bind-mounted volumes writable on the host
# (the platform or operator can chown -R 10001:10001 ./data if needed).
RUN groupadd --gid 10001 nexus \
 && useradd --uid 10001 --gid nexus --no-create-home --shell /usr/sbin/nologin nexus

COPY --from=builder /wheels /wheels
COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN pip install --no-index --find-links=/wheels -r /tmp/requirements-docker.txt \
 && rm -rf /wheels /tmp/requirements-docker.txt

WORKDIR /app
COPY --chown=nexus:nexus . /app

# Runtime state lives in volumes; create them owned by the app user so a fresh
# container never starts with unwritable dirs.
RUN mkdir -p /app/data /app/logs /app/memory /app/backups \
 && chown -R nexus:nexus /app/data /app/logs /app/memory /app/backups

USER nexus

EXPOSE 8000

# Liveness only: /api/health must answer without Postgres/Redis being up.
# Dependency state is /api/ready (used by compose's depends_on + platforms).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json,sys,urllib.request;\
r=urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4);\
sys.exit(0 if r.status==200 else 1)"

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
