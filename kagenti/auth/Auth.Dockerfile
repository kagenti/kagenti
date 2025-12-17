# Use minimal Python base image for all targets
FROM python:3.12.3-slim AS base

# Set work directory
WORKDIR /app

# ---------- Agent OAuth Secret target ----------
FROM base AS agent-auth

# Then copy your script
COPY agent_oauth_secret/agent_oauth_secret.py .

# Add a non-root user and switch to it
RUN useradd -m -u 1001 appuser
USER appuser
CMD ["python", "agent_oauth_secret.py"]


# ---------- Client registration target ----------
FROM base AS client-reg

# Copy your script
COPY client-registration/client_registration.py .

# Register client
CMD ["python", "client_registration.py"]


# ---------- UI OAuth target ----------
FROM base AS ui-auth

# Copy your script
COPY ui-oauth-secret/auth_secret.py .

# Register client
CMD ["python", "auth_secret.py"]