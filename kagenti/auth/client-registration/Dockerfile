# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Create Python package structure and copy identity module
RUN mkdir -p /app/kagenti
COPY kagenti/identity /app/kagenti/identity
RUN touch /app/kagenti/__init__.py

# Set PYTHONPATH so kagenti module can be imported
ENV PYTHONPATH=/app:$PYTHONPATH

# Copy your script
COPY kagenti/auth/client-registration/client_registration.py .

# Install dependencies
COPY kagenti/auth/client-registration/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Register client
CMD ["python", "client_registration.py"]
