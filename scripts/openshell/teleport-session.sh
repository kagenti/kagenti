#!/usr/bin/env bash
# ============================================================================
# TELEPORT SESSION
# ============================================================================
# Package local Claude Code context and deploy it into a Kagenti OpenShell
# sandbox. Enables remote execution of Claude Code with full isolation
# (Landlock, seccomp, netns, OPA) while preserving local skills and config.
#
# Usage:
#   teleport-session.sh --package                        # Bundle context → ConfigMap
#   teleport-session.sh --deploy --session <id>          # Create sandbox with context
#   teleport-session.sh --prompt --session <id> "text"   # Send instruction, get result
#   teleport-session.sh --cleanup --session <id>         # Delete sandbox + ConfigMap
#   teleport-session.sh --full "text"                    # All-in-one: package → deploy → prompt → cleanup
#
# Prerequisites: kubectl, Sandbox CRD installed, LiteLLM proxy running
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

NS="${TELEPORT_NS:-team1}"
TIMEOUT=90
PROMPT_TIMEOUT=120
SESSION_ID=""
ACTION=""
PROMPT_TEXT=""
MAX_CONTEXT_KB=800

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1" >&2; }
log_success() { echo -e "${GREEN}✓${NC} $1" >&2; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1" >&2; }
log_error()   { echo -e "${RED}✗${NC} $1" >&2; }

usage() {
  echo "Usage: teleport-session.sh <action> [options]"
  echo ""
  echo "Actions:"
  echo "  --package              Bundle local context into a ConfigMap"
  echo "  --deploy               Create sandbox with mounted context"
  echo "  --spawn                Create bare sandbox (no local context)"
  echo "  --prompt \"text\"        Send instruction and get result"
  echo "  --cleanup              Delete sandbox and ConfigMap"
  echo "  --full \"text\"          All-in-one: package → deploy → prompt → cleanup"
  echo ""
  echo "Options:"
  echo "  --namespace <ns>       Target namespace (default: team1)"
  echo "  --session <id>         Session ID (auto-generated for --package)"
  echo "  --timeout <secs>       Prompt timeout (default: 120)"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --package)     ACTION="package"; shift ;;
    --deploy)      ACTION="deploy"; shift ;;
    --spawn)       ACTION="spawn"; shift ;;
    --prompt)      ACTION="prompt"; PROMPT_TEXT="${2:-}"; shift 2 ;;
    --cleanup)     ACTION="cleanup"; shift ;;
    --full)        ACTION="full"; PROMPT_TEXT="${2:-}"; shift 2 ;;
    --namespace)   NS="$2"; shift 2 ;;
    --session)     SESSION_ID="$2"; shift 2 ;;
    --timeout)     PROMPT_TIMEOUT="$2"; shift 2 ;;
    --help|-h)     usage; exit 0 ;;
    *)             if [ -z "$PROMPT_TEXT" ] && [ "$ACTION" = "prompt" -o "$ACTION" = "full" ]; then
                     PROMPT_TEXT="$1"; shift
                   else
                     log_error "Unknown option: $1"; usage; exit 1
                   fi ;;
  esac
done

if [ -z "$ACTION" ]; then
  log_error "No action specified"
  usage
  exit 1
fi

generate_session_id() {
  head -c 4 /dev/urandom | xxd -p
}

configmap_name() { echo "teleport-ctx-${SESSION_ID}"; }
sandbox_name()   { echo "teleport-${SESSION_ID}"; }

# ── Package ─────────────────────────────────────────────────────
do_package() {
  if [ -z "$SESSION_ID" ]; then
    SESSION_ID=$(generate_session_id)
  fi
  log_info "Packaging context for session $SESSION_ID"

  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf $tmpdir" RETURN

  # Collect CLAUDE.md
  if [ -f "$REPO_ROOT/CLAUDE.md" ]; then
    cp "$REPO_ROOT/CLAUDE.md" "$tmpdir/CLAUDE.md"
    log_info "  CLAUDE.md ($(wc -c < "$REPO_ROOT/CLAUDE.md") bytes)"
  else
    log_warn "  No CLAUDE.md found at $REPO_ROOT"
  fi

  # Collect skills (SKILL.md files, encode : → _ in names)
  # Only include skills explicitly listed in TELEPORT_SKILLS env var,
  # or skip skills entirely if not set (keeps ConfigMap small).
  local skill_count=0
  if [ -n "${TELEPORT_SKILLS:-}" ] && [ -d "$REPO_ROOT/.claude/skills" ]; then
    IFS=',' read -ra SKILL_LIST <<< "$TELEPORT_SKILLS"
    for skill_name in "${SKILL_LIST[@]}"; do
      skill_name=$(echo "$skill_name" | xargs)
      local skill_file="$REPO_ROOT/.claude/skills/$skill_name/SKILL.md"
      if [ -f "$skill_file" ]; then
        local encoded
        encoded=$(echo "$skill_name" | tr ':/' '__')
        cp "$skill_file" "$tmpdir/skill--${encoded}.md"
        skill_count=$((skill_count + 1))
      fi
    done
    log_info "  Skills: $skill_count selected"
  else
    log_info "  Skills: none (set TELEPORT_SKILLS=name1,name2 to include)"
  fi

  # Collect settings (strip sensitive fields)
  if [ -f "$REPO_ROOT/.claude/settings.json" ]; then
    if command -v python3 &>/dev/null; then
      python3 -c "
import json, sys
with open('$REPO_ROOT/.claude/settings.json') as f:
    s = json.load(f)
sensitive = ['key', 'token', 'secret', 'password', 'credential', 'auth']
for k in list(s.keys()):
    if any(p in k.lower() for p in sensitive):
        del s[k]
json.dump(s, sys.stdout, indent=2)
" > "$tmpdir/settings.json"
    else
      cp "$REPO_ROOT/.claude/settings.json" "$tmpdir/settings.json"
    fi
    log_info "  settings.json"
  fi

  # Collect memory index
  local memory_dir="$HOME/.claude/projects"
  if [ -d "$REPO_ROOT/.claude/memory" ]; then
    memory_dir="$REPO_ROOT/.claude/memory"
  fi
  # Skip memory for now — it's user-specific and may contain sensitive data

  # Size guard
  local total_kb
  total_kb=$(du -sk "$tmpdir" | awk '{print $1}')
  if [ "$total_kb" -gt "$MAX_CONTEXT_KB" ]; then
    log_error "Context too large: ${total_kb}KB > ${MAX_CONTEXT_KB}KB limit"
    log_error "ConfigMap max is ~1MB. Consider reducing skills or using --pvc (future)"
    exit 1
  fi
  log_info "  Total: ${total_kb}KB (limit: ${MAX_CONTEXT_KB}KB)"

  # Create ConfigMap
  local cm_name
  cm_name=$(configmap_name)
  kubectl create configmap "$cm_name" \
    --from-file="$tmpdir" \
    --namespace "$NS" \
    --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null

  log_success "ConfigMap $cm_name created in $NS (session: $SESSION_ID)"
  echo "$SESSION_ID"
}

# ── Deploy ───────────────────────────────────────────────────────
do_deploy() {
  if [ -z "$SESSION_ID" ]; then
    log_error "--session required for --deploy"
    exit 1
  fi

  local sb_name cm_name
  sb_name=$(sandbox_name)
  cm_name=$(configmap_name)

  # Verify ConfigMap exists
  if ! kubectl get configmap "$cm_name" -n "$NS" &>/dev/null; then
    log_error "ConfigMap $cm_name not found. Run --package first."
    exit 1
  fi

  log_info "Deploying sandbox $sb_name with context from $cm_name"

  # Detect LiteLLM URL
  local litellm_url="http://litellm-model-proxy.${NS}.svc:4000"

  # Create Sandbox CR
  kubectl apply -f - <<EOSANDBOX
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: $sb_name
  namespace: $NS
  labels:
    kagenti.io/teleport-session: "$SESSION_ID"
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: ghcr.io/nvidia/openshell-community/sandboxes/base:latest
        command: ["sleep", "3600"]
        env:
        - name: ANTHROPIC_BASE_URL
          value: "${litellm_url}"
        - name: ANTHROPIC_AUTH_TOKEN
          valueFrom:
            secretKeyRef:
              name: litellm-virtual-keys
              key: api-key
              optional: true
        volumeMounts:
        - name: teleport-context
          mountPath: /workspace/.claude-context
          readOnly: true
      volumes:
      - name: teleport-context
        configMap:
          name: $cm_name
EOSANDBOX

  # Wait for pod
  log_info "Waiting for sandbox pod (up to ${TIMEOUT}s)..."
  local deadline=$((SECONDS + TIMEOUT))
  local pod_name=""
  while [ $SECONDS -lt $deadline ]; do
    pod_name=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null \
      | grep "$sb_name" | grep -v Terminating | awk '{print $1}' | head -1 || true)
    if [ -n "$pod_name" ]; then
      local phase
      phase=$(kubectl get pod "$pod_name" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || true)
      if [ "$phase" = "Running" ]; then
        break
      fi
    fi
    sleep 5
  done

  if [ -z "$pod_name" ]; then
    local all_pods
    all_pods=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep "$sb_name" || true)
    if [ -n "$all_pods" ]; then
      log_error "Sandbox pod exists but not Running after ${TIMEOUT}s:"
      log_error "  $all_pods"
      local events
      events=$(kubectl get events -n "$NS" --field-selector "involvedObject.name=$sb_name" --sort-by='.lastTimestamp' 2>/dev/null | tail -5 || true)
      if [ -n "$events" ]; then
        log_error "  Events: $events"
      fi
    else
      log_error "Sandbox pod not created after ${TIMEOUT}s"
      log_error "  Check: kubectl get sandbox $sb_name -n $NS -o yaml"
      log_error "  Controller: kubectl logs -n agent-sandbox-system deploy/agent-sandbox-controller --tail=20"
    fi
    exit 1
  fi

  log_success "Sandbox pod $pod_name running"

  # Unpack context inside the pod
  log_info "Unpacking context in sandbox..."
  kubectl exec "$pod_name" -n "$NS" -c sandbox -- sh -c '
    DEST="$HOME"
    mkdir -p "$DEST/.claude/skills"
    # Copy CLAUDE.md
    [ -f /workspace/.claude-context/CLAUDE.md ] && \
      cp /workspace/.claude-context/CLAUDE.md "$DEST/CLAUDE.md"
    # Copy settings
    [ -f /workspace/.claude-context/settings.json ] && \
      cp /workspace/.claude-context/settings.json "$DEST/.claude/settings.json"
    # Unpack skills (skill--name.md → .claude/skills/name/SKILL.md)
    for f in /workspace/.claude-context/skill--*.md; do
      [ -f "$f" ] || continue
      skill_encoded=$(basename "$f" | sed "s/^skill--//" | sed "s/\.md$//")
      skill_name=$(echo "$skill_encoded" | tr "_" "/" | sed "s|//|/|g")
      mkdir -p "$DEST/.claude/skills/$skill_name"
      cp "$f" "$DEST/.claude/skills/$skill_name/SKILL.md"
    done
    echo "Context unpacked to $DEST: $(ls "$DEST/CLAUDE.md" 2>/dev/null && echo CLAUDE.md) $(find "$DEST/.claude/skills" -name SKILL.md 2>/dev/null | wc -l) skills"
  ' || log_warn "Context unpack had warnings (non-fatal)"

  log_success "Sandbox deployed and context loaded (session: $SESSION_ID)"
}

# ── Spawn (bare sandbox, no context) ────────────────────────────
do_spawn() {
  if [ -z "$SESSION_ID" ]; then
    SESSION_ID=$(generate_session_id)
  fi

  local sb_name
  sb_name=$(sandbox_name)

  local litellm_url="http://litellm-model-proxy.${NS}.svc:4000"

  log_info "Spawning bare sandbox $sb_name (no local context)"

  kubectl apply -f - <<EOSANDBOX
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: $sb_name
  namespace: $NS
  labels:
    kagenti.io/teleport-session: "$SESSION_ID"
spec:
  podTemplate:
    spec:
      containers:
      - name: sandbox
        image: ghcr.io/nvidia/openshell-community/sandboxes/base:latest
        command: ["sleep", "3600"]
        env:
        - name: ANTHROPIC_BASE_URL
          value: "${litellm_url}"
        - name: ANTHROPIC_AUTH_TOKEN
          valueFrom:
            secretKeyRef:
              name: litellm-virtual-keys
              key: api-key
              optional: true
EOSANDBOX

  log_info "Waiting for sandbox pod (up to ${TIMEOUT}s)..."
  local deadline=$((SECONDS + TIMEOUT))
  local pod_name=""
  while [ $SECONDS -lt $deadline ]; do
    pod_name=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null \
      | grep "$sb_name" | grep -v Terminating | awk '{print $1}' | head -1 || true)
    if [ -n "$pod_name" ]; then
      local phase
      phase=$(kubectl get pod "$pod_name" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || true)
      if [ "$phase" = "Running" ]; then
        break
      fi
    fi
    sleep 5
  done

  if [ -z "$pod_name" ]; then
    local all_pods
    all_pods=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep "$sb_name" || true)
    if [ -n "$all_pods" ]; then
      log_error "Sandbox pod exists but not Running after ${TIMEOUT}s:"
      log_error "  $all_pods"
      kubectl describe pod -n "$NS" -l "kagenti.io/teleport-session=$SESSION_ID" 2>/dev/null \
        | grep -A5 "Events:" >&2 || true
    else
      log_error "Sandbox pod not created after ${TIMEOUT}s"
      log_error "  Sandbox CR: $(kubectl get sandbox "$sb_name" -n "$NS" -o jsonpath='{.status}' 2>/dev/null || echo 'not found')"
      log_error "  Controller: kubectl logs -n agent-sandbox-system deploy/agent-sandbox-controller --tail=10"
    fi
    exit 1
  fi

  log_success "Sandbox $sb_name running (session: $SESSION_ID)"
  log_info "Send prompts:  $0 --session $SESSION_ID --prompt \"your task\""
  log_info "Cleanup:       $0 --session $SESSION_ID --cleanup"
  echo "$SESSION_ID"
}

# ── Prompt ───────────────────────────────────────────────────────
do_prompt() {
  if [ -z "$SESSION_ID" ]; then
    log_error "--session required for --prompt"
    exit 1
  fi
  if [ -z "$PROMPT_TEXT" ]; then
    log_error "No prompt text provided"
    exit 1
  fi

  local sb_name pod_name
  sb_name=$(sandbox_name)

  # Wait briefly for pod to be Running (may be restarting)
  local deadline=$((SECONDS + 30))
  while [ $SECONDS -lt $deadline ]; do
    pod_name=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null \
      | grep "$sb_name" | grep -v Terminating | grep Running | awk '{print $1}' | head -1 || true)
    [ -n "$pod_name" ] && break
    sleep 3
  done

  if [ -z "$pod_name" ]; then
    log_error "No running pod for session $SESSION_ID (sandbox: $sb_name)"
    exit 1
  fi

  log_info "Sending prompt to $pod_name (timeout: ${PROMPT_TIMEOUT}s)..."
  kubectl exec "$pod_name" -n "$NS" -c sandbox -- \
    timeout "$PROMPT_TIMEOUT" claude --print --bare \
    --model claude-sonnet-4-20250514 \
    "$PROMPT_TEXT"
}

# ── Cleanup ──────────────────────────────────────────────────────
do_cleanup() {
  if [ -z "$SESSION_ID" ]; then
    log_error "--session required for --cleanup"
    exit 1
  fi

  local sb_name cm_name
  sb_name=$(sandbox_name)
  cm_name=$(configmap_name)

  log_info "Cleaning up session $SESSION_ID..."
  kubectl delete sandbox "$sb_name" -n "$NS" --ignore-not-found --wait=false 2>/dev/null || true
  kubectl delete configmap "$cm_name" -n "$NS" --ignore-not-found 2>/dev/null || true

  # Wait for pod to terminate
  local deadline=$((SECONDS + 30))
  while [ $SECONDS -lt $deadline ]; do
    if ! kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep -q "$sb_name"; then
      break
    fi
    sleep 2
  done

  log_success "Session $SESSION_ID cleaned up"
}

# ── Full (all-in-one) ────────────────────────────────────────────
do_full() {
  if [ -z "$PROMPT_TEXT" ]; then
    log_error "No prompt text provided for --full"
    exit 1
  fi

  SESSION_ID=$(do_package | tail -1)
  do_deploy
  echo "" >&2
  echo -e "${GREEN}═══════════════════════════════════════════════${NC}" >&2
  do_prompt
  echo -e "${GREEN}═══════════════════════════════════════════════${NC}" >&2
  echo "" >&2
  do_cleanup
}

# ── Main ─────────────────────────────────────────────────────────
case "$ACTION" in
  package) do_package ;;
  deploy)  do_deploy ;;
  spawn)   do_spawn ;;
  prompt)  do_prompt ;;
  cleanup) do_cleanup ;;
  full)    do_full ;;
  *)       log_error "Unknown action: $ACTION"; usage; exit 1 ;;
esac
