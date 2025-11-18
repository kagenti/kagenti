# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Create Python package structure
RUN mkdir -p /app/kagenti
RUN touch /app/kagenti/__init__.py

# Copy identity module from build context
# Note: The identity module must be copied into kagenti/auth/identity/ 
# before building (done automatically in CI workflows)
COPY identity /app/kagenti/identity

# Set PYTHONPATH so kagenti module can be imported
ENV PYTHONPATH=/app

# Copy your script
COPY client-registration/client_registration.py .

# Install dependencies
COPY client-registration/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Register client
CMD ["python", "client_registration.py"]
