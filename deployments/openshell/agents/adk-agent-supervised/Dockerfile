# ADK agent with OpenShell supervisor as entrypoint
# Supervisor applies Landlock + seccomp + netns + OPA before exec'ing the agent
FROM ghcr.io/rossoctl/openshell/supervisor:v0.0.36-rossoctl.8 AS supervisor

FROM python:3.13-slim

# iproute2 needed for supervisor netns creation, bash for entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 bash && \
    rm -rf /var/lib/apt/lists/*

# Supervisor requires a 'sandbox' user to drop privileges to
RUN groupadd -f sandbox && \
    id sandbox >/dev/null 2>&1 || useradd -r -g sandbox -d /home/sandbox -m -s /bin/bash sandbox && \
    mkdir -p /home/sandbox /.cache /tmp /var/log && \
    chown -R sandbox:sandbox /home/sandbox /.cache /tmp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
RUN chown -R sandbox:sandbox /app

# Copy supervisor binary from OpenShell image
COPY --from=supervisor /openshell-sandbox /usr/local/bin/openshell-sandbox

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/openshell-sandbox"]
CMD ["--", "python", "agent.py"]
