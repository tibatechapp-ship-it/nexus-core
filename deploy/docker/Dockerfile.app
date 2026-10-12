# ═══ Stage 1: Builder ═══
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies if needed (gcc for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage caching
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ═══ Stage 2: Runtime ═══
FROM python:3.12-slim

LABEL maintainer="Hive Team"
LABEL description="Novamind Core & Dashboard"

# Create non-root user for security
RUN groupadd -r hiveuser && useradd -r -g hiveuser hiveuser

WORKDIR /app

# Copy wheels from builder
COPY --from=builder /wheels /wheels
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Install runtime deps only
RUN pip install --no-cache-dir --no-index --find-links=/wheels/ /wheels/* \
    && rm -rf /wheels

# Copy application code
COPY . /app

# Set ownership
RUN chown -R hiveuser:hiveuser /app

USER hiveuser

# Expose port for Dashboard
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Command to run the dashboard (which loads orchestrator internally)
CMD ["python", "-m", "hive.agents.dashboard"]
