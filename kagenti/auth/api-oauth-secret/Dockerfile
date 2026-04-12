# Use minimal Python base image
FROM python:3.14-slim@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca

# Set work directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY auth/api-oauth-secret/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY auth/api-oauth-secret/register_api_client.py .

# Create non-root user for runtime security
RUN useradd -u 1001 -m appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER 1001

# Register API client
CMD ["python", "register_api_client.py"]
