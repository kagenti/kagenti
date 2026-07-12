#!/usr/bin/env bash
# Seed a simulated "Tasks API" tool into a namespace and wait until it is Ready.
# Usage: seed.sh [NAMESPACE] [TOOL_NAME]
#   NAMESPACE  target namespace (default: team1)
#   TOOL_NAME  simulated tool name (default: tasks-api)
# Env:
#   KAGENTI_BACKEND_URL  backend API base (default: http://localhost:8002)
#   KEYCLOAK_URL         Keycloak base (default: http://localhost:8081)
#   LLM_SECRET_NAME/LLM_SECRET_KEY  LLM key Secret (default: llm-api-key/apiKey)
set -euo pipefail

NAMESPACE="${1:-team1}"
TOOL_NAME="${2:-tasks-api}"
BACKEND_URL="${KAGENTI_BACKEND_URL:-http://localhost:8002}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8081}"
LLM_SECRET_NAME="${LLM_SECRET_NAME:-llm-api-key}"
LLM_SECRET_KEY="${LLM_SECRET_KEY:-apiKey}"
SPEC_FILE="$(dirname "$0")/openapi.json"
LOG="${LOG_DIR:-/tmp}/seed-simulated-tool.log"

echo "Acquiring Keycloak token..."
KC_USER="$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)"
KC_PASS="$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)"
TOKEN="$(curl -sf "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=admin-cli \
  -d "username=${KC_USER}" -d "password=${KC_PASS}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"

echo "Creating simulated tool '${TOOL_NAME}' in namespace '${NAMESPACE}'..."
SPEC_JSON="$(python3 -c 'import json,sys;print(json.dumps(open(sys.argv[1]).read()))' "${SPEC_FILE}")"
BODY="$(cat <<EOF
{"namespace":"${NAMESPACE}","name":"${TOOL_NAME}","openapiSpec":${SPEC_JSON},
 "envVars":[{"name":"LLM_API_KEY","valueFrom":{"secretKeyRef":{"name":"${LLM_SECRET_NAME}","key":"${LLM_SECRET_KEY}"}}}]}
EOF
)"
curl -sf -X POST "${BACKEND_URL}/api/v1/simulation/tools" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d "${BODY}" > "${LOG}" 2>&1
echo "Create accepted; waiting for Ready (see ${LOG})..."

for _ in $(seq 1 120); do
  STATUS_JSON="$(curl -sf "${BACKEND_URL}/api/v1/simulation/tools/${NAMESPACE}/${TOOL_NAME}/generation-status" \
    -H "Authorization: Bearer ${TOKEN}" || true)"
  STATUS="$(echo "${STATUS_JSON}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))' 2>/dev/null || echo "")"
  case "${STATUS}" in
    Ready)
      MCP_URL="$(echo "${STATUS_JSON}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("mcpUrl",""))')"
      echo "Ready. mcpUrl=${MCP_URL}"; exit 0 ;;
    Failed|Error)
      REASON="$(echo "${STATUS_JSON}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("reason",""))')"
      echo "Generation ${STATUS}: ${REASON}" >&2; exit 1 ;;
    *) sleep 5 ;;
  esac
done
echo "Timed out waiting for Ready." >&2; exit 1
