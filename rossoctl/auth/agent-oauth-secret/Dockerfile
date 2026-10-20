# This file has been modified with the assistance of Bob

# Use minimal Python base image
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

# Set work directory
WORKDIR /app

# Install dependencies from requirements.txt
COPY auth/agent-oauth-secret/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common utilities from unified context
COPY common/ ./common/

# Copy auth shared utilities
COPY auth/shared_utils.py ./rossoctl/auth/

# Copy the script
COPY auth/agent-oauth-secret/agent_oauth_secret.py .

# Create non-root user for runtime security
RUN useradd -u 1001 -m appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER 1001

# Run the agent OAuth setup
CMD ["python", "agent_oauth_secret.py"]