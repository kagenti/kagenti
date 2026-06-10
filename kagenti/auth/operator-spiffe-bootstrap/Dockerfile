# This file has been modified with the assistance of Claude Code

# Use minimal Python base image
FROM python:3.14-slim@sha256:5b3879b6f3cb77e712644d50262d05a7c146b7312d784a18eff7ff5462e77033

# Set work directory
WORKDIR /app

# Install dependencies with hash verification
COPY kagenti/auth/operator-spiffe-bootstrap/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script
COPY kagenti/auth/operator-spiffe-bootstrap/setup_operator_client.py .

# Create non-root user for runtime security
RUN useradd -u 1001 -m appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER 1001

# Run the setup script
CMD ["python3", "setup_operator_client.py"]
