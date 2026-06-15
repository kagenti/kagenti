# Hermes Agent — ACP mode for Kagenti integration
#
# Hermes v0.15.1 with ACP adapter for IDE/CLI agent communication.
# Uses LiteLLM proxy for model routing (Vertex AI, MaaS, etc.)
#
# Based on: NousResearch/hermes-agent v2026.5.29

FROM python:3.13-slim

ARG HERMES_VERSION=v2026.5.29

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r agent && useradd -r -g agent -d /sandbox -s /bin/bash agent \
    && mkdir -p /sandbox/.hermes /sandbox/.hermes-data/memories \
        /sandbox/.hermes-data/sessions /sandbox/.hermes-data/skills \
        /sandbox/.hermes-data/plugins /sandbox/.hermes-data/workspace \
        /sandbox/.hermes-data/logs /sandbox/.hermes-data/cache \
    && chown -R agent:agent /sandbox

# hadolint ignore=DL3013
RUN pip install --no-cache-dir \
        "hermes-agent[acp] @ https://github.com/NousResearch/hermes-agent/archive/refs/tags/${HERMES_VERSION}.tar.gz" \
        "pyyaml==6.0.3" \
    && hermes --version

# Patch custom_providers model resolution (upstream: NousResearch/hermes-agent#34500)
COPY patch-custom-providers.py /tmp/patch-custom-providers.py
RUN python3 /tmp/patch-custom-providers.py && rm /tmp/patch-custom-providers.py

# Startup: configure LiteLLM as provider, then run hermes chat in single-query mode
# The deployment.yaml passes the actual command via args
# hadolint ignore=SC2016
RUN echo '#!/bin/sh' > /usr/local/bin/start-hermes.sh \
    && echo 'set -e' >> /usr/local/bin/start-hermes.sh \
    && echo 'mkdir -p "$HOME/.hermes" "$HOME/.hermes-data/memories" "$HOME/.hermes-data/logs"' >> /usr/local/bin/start-hermes.sh \
    && echo '# Write LiteLLM provider config from env vars' >> /usr/local/bin/start-hermes.sh \
    && echo 'cat > "$HOME/.hermes/config.yaml" << EOF' >> /usr/local/bin/start-hermes.sh \
    && echo 'model:' >> /usr/local/bin/start-hermes.sh \
    && echo '  default: ${LLM_MODEL:-claude-sonnet-4-20250514}' >> /usr/local/bin/start-hermes.sh \
    && echo '  provider: kagenti' >> /usr/local/bin/start-hermes.sh \
    && echo 'custom_providers:' >> /usr/local/bin/start-hermes.sh \
    && echo '  - name: kagenti' >> /usr/local/bin/start-hermes.sh \
    && echo '    base_url: ${OPENAI_API_BASE:-http://litellm-model-proxy.team1.svc:4000/v1}' >> /usr/local/bin/start-hermes.sh \
    && echo '    api_key: ${OPENAI_API_KEY}' >> /usr/local/bin/start-hermes.sh \
    && echo '    models:' >> /usr/local/bin/start-hermes.sh \
    && echo '      - ${LLM_MODEL:-claude-sonnet-4-20250514}' >> /usr/local/bin/start-hermes.sh \
    && echo 'EOF' >> /usr/local/bin/start-hermes.sh \
    && echo 'exec "$@"' >> /usr/local/bin/start-hermes.sh \
    && chmod +x /usr/local/bin/start-hermes.sh

USER agent
ENV HOME=/sandbox
WORKDIR /sandbox

EXPOSE 8642
ENTRYPOINT ["/usr/local/bin/start-hermes.sh"]
CMD ["sleep", "infinity"]
