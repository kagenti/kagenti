# Use minimal Python base image
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Copy your script
COPY agent_oauth_secret.py .

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "agent_oauth_secret.py"]