# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Copy your script
COPY auth_secret.py .

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Register client
CMD ["python", "auth_secret.py"]