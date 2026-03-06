FROM kagenti-agent-base:latest

# Install Node.js for OpenCode CLI
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI
RUN npm install -g opencode@latest

# Copy OpenCode agent wrapper
COPY agents/opencode/ /app/opencode/

USER 1001

ENV AGENT_MODULE=opencode.plugin \
    AGENT_NAME=opencode-agent \
    OPENCODE_PORT=19876

EXPOSE 8000 19876

CMD ["python", "-m", "platform_base.entrypoint"]
