#!/bin/bash
set -e

CONFIG_DIR="${ROSSOCORTEX_CONFIG_DIR:-/etc/rossocortex}"
CA_DIR="$CONFIG_DIR/ca"
CREDENTIALS_DIR="$CONFIG_DIR/credentials"
PORT="${ROSSOCORTEX_PORT:-8180}"
CONTROL_PORT="${ROSSOCORTEX_CONTROL_PORT:-8181}"
BUDGET="${ROSSOCORTEX_DAILY_BUDGET:-5.00}"
UPSTREAM="${ROSSOCORTEX_UPSTREAM:-}"

# Generate CA if not mounted
if [ ! -f "$CA_DIR/tls.crt" ]; then
    echo "Generating TLS-bridge CA certificate..."
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
        -subj '/CN=Rosscortex Local CA/O=kagenti' \
        -addext 'basicConstraints=critical,CA:TRUE' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' \
        -keyout "$CA_DIR/tls.key" -out "$CA_DIR/tls.crt" 2>/dev/null
    chmod 600 "$CA_DIR/tls.key"
fi

# Write credentials from environment variables if files don't exist
for var in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN OPENAI_API_KEY LITELLM_API_KEY; do
    val="${!var}"
    if [ -n "$val" ] && [ ! -f "$CREDENTIALS_DIR/$var" ]; then
        echo "$val" > "$CREDENTIALS_DIR/$var"
        chmod 600 "$CREDENTIALS_DIR/$var"
    fi
done

# Always regenerate authbridge config with container paths
AUTHBRIDGE_CONFIG="$CONFIG_DIR/config.yaml"
if true; then
    AUTHBRIDGE_PORT=3130
    cat > "$AUTHBRIDGE_CONFIG" <<EOF
mode: proxy-sidecar

listener:
  reverse_proxy_addr: ":18081"
  forward_proxy_addr: "0.0.0.0:${AUTHBRIDGE_PORT}"
  transparent_proxy_addr: ":18082"
  reverse_proxy_backend: "http://127.0.0.1:1"
  session_api_addr: ":19095"

tls_bridge:
  mode: enabled
  ca_dir: ${CA_DIR}
  ports: [443]

session:
  enabled: true

stats:
  address: ":19096"

pipeline:
  outbound:
    plugins:
      - name: placeholder-resolve
        config:
          source: secret_dir
          secret_dir: ${CREDENTIALS_DIR}
      - name: inference-parser
      - name: mcp-parser
  inbound:
    plugins:
      - name: litellm-budget-track
        config:
          spend_file: ${CONFIG_DIR}/spend-authbridge.json
          max_budget: ${BUDGET}
EOF
fi

# Copy agents.json if mounted
if [ -f "/etc/rossocortex/agents.json" ]; then
    cp /etc/rossocortex/agents.json "$CONFIG_DIR/agents.json" 2>/dev/null || true
fi

echo "rossocortex container starting"
echo "  Port:        ${PORT}"
echo "  Control:     ${CONTROL_PORT}"
echo "  Budget:      \$${BUDGET}/day"
echo "  Upstream:    ${UPSTREAM:-<not set, pass ROSSOCORTEX_UPSTREAM>}"
echo "  Credentials: $(ls "$CREDENTIALS_DIR" 2>/dev/null | tr '\n' ' ')"
echo "  CA:          ${CA_DIR}/tls.crt"
echo "---"

if [ -z "$UPSTREAM" ]; then
    echo "ERROR: ROSSOCORTEX_UPSTREAM is required" >&2
    exit 1
fi

exec python3 /app/rossocortex.py \
    --budget "$BUDGET" \
    --upstream "$UPSTREAM" \
    --port "$PORT" \
    --control-port "$CONTROL_PORT" \
    --authbridge-config "$AUTHBRIDGE_CONFIG"
