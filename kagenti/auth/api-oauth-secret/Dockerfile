# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY register_api_client.py .

# Create non-root user for runtime security
RUN useradd -u 1001 -m appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER 1001

# Register API client
CMD ["python", "register_api_client.py"]
