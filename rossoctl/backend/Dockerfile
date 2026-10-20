# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

# Stage 1: Build stage with uv
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.24@sha256:816fdce3387ed2142e37d2e56e1b1b97ccc1ea87731ba199dc8a25c04e4997c5 /uv /bin/uv

# Copy dependency files
COPY backend/pyproject.toml ./

# Create virtual environment and install dependencies (not the app package itself —
# the runtime stage copies fresh source via COPY backend/app/)
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv pip install --no-cache -r pyproject.toml

# Stage 2: Runtime stage
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

WORKDIR /app

# Install CA certificates and update certificate store for SSL verification
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        openssl && \
    update-ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r -g 1001 appgroup && useradd -r -u 1001 -g appgroup appuser

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY backend/app/ ./app/

# Bake the release tag in as the reported backend version. Mirrors what
# ui-v2/Dockerfile does to package.json, so the backend's GET /auth/config and the
# UI's version badge report the same string from the same source. CI passes
# RELEASE_TAG for every image in the build matrix (.github/workflows/build.yaml).
ARG RELEASE_TAG=unknown
ENV ROSSOCTL_BACKEND_VERSION=${RELEASE_TAG}

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Unset SSL_CERT_FILE to prevent Kubernetes service account CA from being used
# Python will use the system CA bundle at /etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=""
ENV SSL_CERT_DIR=/etc/ssl/certs
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Change ownership
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER 1001

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
