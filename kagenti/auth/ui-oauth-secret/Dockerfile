# This file has been modified with the assistance of Bob

# Use minimal Python base image
FROM python:3.14-slim@sha256:bc389f7dfcb21413e72a28f491985326994795e34d2b86c8ae2f417b4e7818aa

# Set work directory
WORKDIR /app

# Install dependencies from requirements.txt
COPY auth/ui-oauth-secret/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common utilities from unified context
COPY common/ ./common/

# Copy auth shared utilities
COPY auth/shared_utils.py ./kagenti/auth/

# Copy the script
COPY auth/ui-oauth-secret/auth_secret.py .

# Create non-root user for runtime security
RUN useradd -u 1001 -m appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER 1001

# Register client
CMD ["python", "auth_secret.py"]