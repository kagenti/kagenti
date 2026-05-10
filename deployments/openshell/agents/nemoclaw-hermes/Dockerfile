# NemoClaw Hermes Agent — pinned build from upstream source
#
# Installs Hermes Agent (Nous Research) from GitHub release tarball.
# Pinned to NemoClaw v0.0.28 / Hermes v2026.4.13.
#
# Based on: github.com/NVIDIA/NemoClaw/agents/hermes/Dockerfile.base @ v0.0.28
# Simplified: no NemoClaw plugin, no blueprint, no OpenShell supervisor.
# socat bridges from 0.0.0.0:8642 to loopback:15053 for K8s access.

FROM python:3.12-slim@sha256:4386a385d81dba9f72ed72a6fe4237755d7f5440c84b417650f38336bbc43117

ARG HERMES_VERSION=v2026.4.13

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates socat \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r agent && useradd -r -g agent -d /sandbox -s /bin/bash agent \
    && mkdir -p /sandbox/.hermes /sandbox/.hermes-data/memories \
        /sandbox/.hermes-data/sessions /sandbox/.hermes-data/skills \
        /sandbox/.hermes-data/plugins /sandbox/.hermes-data/workspace \
        /sandbox/.hermes-data/logs /sandbox/.hermes-data/cache \
    && chown -R agent:agent /sandbox

# hadolint ignore=DL3013
RUN pip install --no-cache-dir \
        "hermes-agent @ https://github.com/NousResearch/hermes-agent/archive/refs/tags/${HERMES_VERSION}.tar.gz" \
        "pyyaml==6.0.3" \
    && hermes --version

# Startup script: configure + socat bridge + hermes gateway
# hadolint ignore=SC2016
RUN echo '#!/bin/sh' > /usr/local/bin/start-hermes.sh \
    && echo 'set -e' >> /usr/local/bin/start-hermes.sh \
    && echo 'mkdir -p "$HOME/.hermes" "$HOME/.hermes-data/memories" "$HOME/.hermes-data/logs"' >> /usr/local/bin/start-hermes.sh \
    && echo 'echo "GATEWAY_ALLOW_ALL_USERS=true" > "$HOME/.hermes/.env"' >> /usr/local/bin/start-hermes.sh \
    && echo 'hermes config set model "${LLM_MODEL:-gpt-4o-mini}"' >> /usr/local/bin/start-hermes.sh \
    && echo 'socat TCP-LISTEN:8642,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:15053 &' >> /usr/local/bin/start-hermes.sh \
    && echo 'exec hermes gateway run' >> /usr/local/bin/start-hermes.sh \
    && chmod +x /usr/local/bin/start-hermes.sh

USER agent
ENV HOME=/sandbox
WORKDIR /sandbox

EXPOSE 8642
CMD ["/usr/local/bin/start-hermes.sh"]
