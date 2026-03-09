# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Copy your script and ensure it's readable
COPY phoenix_oauth_secret.py .
RUN chmod 644 phoenix_oauth_secret.py

# Install dependencies
COPY requirements.txt .
RUN chmod 644 requirements.txt && pip install --no-cache-dir -r requirements.txt

# OpenShift runs as random UID, ensure /app is accessible
RUN chmod -R g=u /app

# Register client
CMD ["python", "phoenix_oauth_secret.py"]
