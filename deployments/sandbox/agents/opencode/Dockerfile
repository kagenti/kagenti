FROM kagenti-agent-base:latest

# Install Node.js for OpenCode CLI
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI (npm package: oh-my-opencode)
RUN npm install -g opencode-ai@latest

# Copy OpenCode agent wrapper
COPY agents/opencode/ /app/opencode/

# Set permissions for OCP arbitrary UIDs
RUN chown -R 1001:0 /app && chmod -R g+w /app

USER 1001

ENV AGENT_MODULE=opencode.plugin \
    AGENT_NAME=opencode-agent \
    OPENCODE_PORT=4096

EXPOSE 8000 4096

CMD ["python", "-m", "platform_base.entrypoint"]
