# Use minimal Python base image
FROM python:3.14-slim@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca

# Set work directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY auth/mlflow-oauth-secret/requirements.txt .
RUN chmod 644 requirements.txt && pip install --no-cache-dir -r requirements.txt

# Copy scripts and ensure they're readable
COPY auth/mlflow-oauth-secret/mlflow_oauth_secret.py .
RUN chmod 644 mlflow_oauth_secret.py

# OpenShift runs as random UID, ensure /app is accessible
RUN chmod -R g=u /app

# Register client
CMD ["python", "mlflow_oauth_secret.py"]
