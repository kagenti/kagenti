# NemoClaw OpenClaw Agent — pinned build from upstream source
#
# Installs OpenClaw CLI from npm registry.
# Pinned to NemoClaw v0.0.28 / OpenClaw v2026.4.9.
#
# Based on: github.com/NVIDIA/NemoClaw/Dockerfile.base @ v0.0.28
# Simplified: no NemoClaw plugin, no blueprint, no exec-approvals patch.
# socat bridges from 0.0.0.0:8080 to loopback:18789 for K8s access.

FROM node:22-slim@sha256:2fc5ec124496f2fb49b8da251c8b4b674c6b96c1f2176f6c77fa23ec7e9af7d7

ARG OPENCLAW_VERSION=2026.4.9

ENV DEBIAN_FRONTEND=noninteractive

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl git ca-certificates socat \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /home/node/.openclaw /home/node/.openclaw-data \
    && chown -R node:node /home/node

# hadolint ignore=DL3016
RUN npm install -g "openclaw@${OPENCLAW_VERSION}" \
    && openclaw --version

# Startup script: socat bridge + openclaw gateway
# hadolint ignore=SC2016
RUN echo '#!/bin/sh' > /usr/local/bin/start-openclaw.sh \
    && echo 'set -e' >> /usr/local/bin/start-openclaw.sh \
    && echo 'mkdir -p "$HOME/.openclaw" "$HOME/.openclaw-data"' >> /usr/local/bin/start-openclaw.sh \
    && echo 'socat TCP-LISTEN:8080,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:18789 &' >> /usr/local/bin/start-openclaw.sh \
    && echo 'exec openclaw gateway run --allow-unconfigured' >> /usr/local/bin/start-openclaw.sh \
    && chmod +x /usr/local/bin/start-openclaw.sh

USER node
WORKDIR /home/node

EXPOSE 8080
CMD ["/usr/local/bin/start-openclaw.sh"]
