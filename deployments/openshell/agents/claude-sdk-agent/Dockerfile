FROM python:3.13-slim

RUN groupadd -r agent && useradd -r -g agent -d /app -s /sbin/nologin agent

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
RUN chown -R agent:agent /app

USER agent
EXPOSE 8080
CMD ["python", "agent.py"]
