#!/usr/bin/env bash
# Interactive Agent Chat Script (A2A JSONRPC Protocol)
# Allows chatting with deployed Kagenti agents from the console using
# the Agent-to-Agent (A2A) protocol with JSONRPC 2.0 message/send method.
#
# Usage:
#   ./local-testing/chat-with-agent.sh                          # Use default weather-service
#   ./local-testing/chat-with-agent.sh <agent-url>              # Custom agent URL
#   ./local-testing/chat-with-agent.sh http://localhost:8000    # Port-forwarded agent
#
# A2A Protocol Reference:
#   - Method: message/send
#   - Request: {"jsonrpc":"2.0","id":"<req-id>","method":"message/send","params":{"id":"<context-id>","message":{"role":"user","parts":[{"type":"text","text":"..."}]}}}
#   - Response: Contains task with artifacts array holding the response parts

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Default agent URL (in-cluster)
DEFAULT_AGENT_URL="http://weather-service.team1.svc.cluster.local:8000"
DEFAULT_AGENT_NAME="weather-service"

# Generate unique IDs for A2A protocol
generate_uuid() {
    uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$$-$RANDOM"
}

# Parse arguments
AGENT_URL="${1:-}"
AGENT_NAME="${2:-custom-agent}"

# If no URL provided, try to detect available agents
if [ -z "$AGENT_URL" ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║              Interactive Agent Chat                           ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Check if platform is running
    if ! kubectl get namespace team1 &> /dev/null; then
        echo -e "${RED}✗ Platform not deployed or team1 namespace not found${NC}"
        echo "  Run: ./local-testing/deploy-platform.sh"
        exit 1
    fi

    # List available agents
    echo -e "${BLUE}Available agents:${NC}"
    echo ""

    AGENTS=$(kubectl get deployments -n team1 -l app.kubernetes.io/component=agent -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.availableReplicas}{"\n"}{end}' 2>/dev/null || echo "")

    if [ -z "$AGENTS" ]; then
        echo -e "${YELLOW}⚠ No agents found in team1 namespace${NC}"
        echo ""
        echo "Deploy the weather agent first:"
        echo "  ./local-testing/deploy-platform.sh"
        exit 1
    fi

    echo "$AGENTS" | while IFS=$'\t' read -r name replicas; do
        if [ "$replicas" = "1" ]; then
            echo -e "  ${GREEN}●${NC} $name (ready)"
        else
            echo -e "  ${RED}○${NC} $name (not ready)"
        fi
    done

    echo ""
    echo -e "${CYAN}Using default agent: ${DEFAULT_AGENT_NAME}${NC}"
    echo -e "${CYAN}Agent URL: ${DEFAULT_AGENT_URL}${NC}"
    echo ""

    AGENT_URL="$DEFAULT_AGENT_URL"
    AGENT_NAME="$DEFAULT_AGENT_NAME"

    # Offer to port-forward
    echo -e "${YELLOW}Note: For in-cluster URLs, you may need to be in a pod or use port-forward${NC}"
    echo ""
    echo "To use port-forward instead, run in another terminal:"
    echo "  kubectl port-forward -n team1 svc/weather-service 8000:8000"
    echo "Then run this script with:"
    echo "  ./local-testing/chat-with-agent.sh http://localhost:8000"
    echo ""
    read -p "Press Enter to continue with in-cluster URL, or Ctrl+C to cancel... "
    echo ""
fi

# Context ID for A2A conversation (persists across messages in a session)
# This corresponds to "context_id" in A2A which groups related tasks
CONTEXT_ID=$(generate_uuid)

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           Agent Chat Session (A2A Protocol)                   ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${CYAN}Agent URL:${NC}     $AGENT_URL"
echo -e "${CYAN}Context ID:${NC}    $CONTEXT_ID"
echo ""
echo -e "${YELLOW}Type your messages and press Enter. Type 'exit', 'quit', or Ctrl+C to end.${NC}"
echo ""
echo "────────────────────────────────────────────────────────────────"
echo ""

# Message counter for request IDs
MSG_COUNT=0

# Chat loop
while true; do
    # Read user input
    echo -ne "${GREEN}You:${NC} "
    read -r USER_MESSAGE

    # Check for exit commands
    if [[ "$USER_MESSAGE" =~ ^(exit|quit|bye)$ ]]; then
        echo ""
        echo -e "${CYAN}Ending chat session. Goodbye!${NC}"
        echo ""
        exit 0
    fi

    # Skip empty messages
    if [ -z "$USER_MESSAGE" ]; then
        continue
    fi

    # Increment message counter
    MSG_COUNT=$((MSG_COUNT + 1))
    REQUEST_ID="req-${CONTEXT_ID}-${MSG_COUNT}"

    # Escape user message for JSON (handle quotes and special characters)
    ESCAPED_MESSAGE=$(echo "$USER_MESSAGE" | jq -Rs '.')

    # Generate unique message ID (required by A2A protocol)
    MESSAGE_ID="msg-${REQUEST_ID}"

    # Prepare A2A JSONRPC payload
    # Using message/send method with proper A2A message structure
    # Key requirements:
    # - parts use "kind" not "type"
    # - messageId is required in the message object
    JSON_PAYLOAD=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "${REQUEST_ID}",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": ${ESCAPED_MESSAGE}}],
      "messageId": "${MESSAGE_ID}"
    }
  }
}
EOF
)

    # Send message to agent (POST to root path for A2A JSONRPC)
    echo -ne "${BLUE}Agent:${NC} "

    RESPONSE=$(curl -s -X POST "$AGENT_URL/" \
        -H "Content-Type: application/json" \
        -d "$JSON_PAYLOAD" \
        --max-time 120 2>&1) || {
        echo -e "${RED}Error: Failed to connect to agent${NC}"
        echo -e "${RED}$RESPONSE${NC}"
        echo ""
        echo "Troubleshooting:"
        echo "  1. Check if agent is running:"
        echo "     kubectl get pods -n team1"
        echo ""
        echo "  2. Check agent logs:"
        echo "     kubectl logs -n team1 deployment/$AGENT_NAME --tail=50"
        echo ""
        echo "  3. If using in-cluster URL, try port-forward:"
        echo "     kubectl port-forward -n team1 deployment/$AGENT_NAME 8000:8000"
        echo "     Then use: ./local-testing/chat-with-agent.sh http://localhost:8000"
        echo ""
        continue
    }

    # Parse A2A JSONRPC response
    if echo "$RESPONSE" | jq -e . >/dev/null 2>&1; then
        # Check for JSONRPC error
        ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error.message // empty')
        if [ -n "$ERROR_MSG" ]; then
            echo -e "${RED}Error: $ERROR_MSG${NC}"
            echo ""
            continue
        fi

        # Extract the agent's response from A2A result
        # A2A response structure: { result: { artifacts: [{ parts: [{ text: "..." }] }] } }
        AGENT_REPLY=$(echo "$RESPONSE" | jq -r '
            .result.artifacts[-1].parts[-1].text //
            .result.status.message.parts[-1].text //
            .result.message //
            "No response received"
        ')

        # Also check task state
        TASK_STATE=$(echo "$RESPONSE" | jq -r '.result.state // empty')

        if [ "$TASK_STATE" = "failed" ]; then
            echo -e "${RED}Task failed: $AGENT_REPLY${NC}"
        else
            echo "$AGENT_REPLY"
        fi

        # Show task ID if available (useful for tracing)
        TASK_ID=$(echo "$RESPONSE" | jq -r '.result.id // empty')
        if [ -n "$TASK_ID" ] && [ "$TASK_ID" != "null" ]; then
            echo -e "${MAGENTA}  [Task: $TASK_ID]${NC}"
        fi
    else
        # Non-JSON response, display as-is
        echo "$RESPONSE"
    fi

    echo ""
done
