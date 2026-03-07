FROM kagenti-agent-base:latest

# Install Legion-specific dependencies (LangGraph + LLM)
COPY requirements.txt /app/legion-requirements.txt
RUN uv pip install --system --no-cache -r /app/legion-requirements.txt

# Copy Legion agent code
COPY agents/legion/ /app/legion/

# Copy config files
COPY agents/legion/settings.json /app/settings.json
COPY agents/legion/sources.json /app/sources.json

ENV AGENT_MODULE=legion.plugin \
    AGENT_NAME=sandbox-legion

CMD ["python", "-m", "platform_base.entrypoint"]
