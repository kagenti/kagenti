FROM python:3.12-alpine

RUN apk add --no-cache openssl ca-certificates bash

# Install Python deps for rossocortex.py
RUN pip install --no-cache-dir httpx>=0.27

# AuthBridge binary (built by build.sh for linux)
COPY bin/authbridge-proxy-linux /usr/local/bin/authbridge-proxy
RUN chmod +x /usr/local/bin/authbridge-proxy

# rossocortex.py — the budget proxy (same as local)
COPY rossocortex.py /app/rossocortex.py
RUN chmod +x /app/rossocortex.py

# Config template for authbridge
COPY templates/ /app/templates/

# Default directories
RUN mkdir -p /etc/rossocortex/ca /etc/rossocortex/credentials /etc/rossocortex/agents

EXPOSE 8180 8181

ENV ROSSOCORTEX_CONFIG_DIR=/etc/rossocortex \
    ROSSOCORTEX_PORT=8180 \
    ROSSOCORTEX_CONTROL_PORT=8181 \
    ROSSOCORTEX_DAILY_BUDGET=5.00

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
