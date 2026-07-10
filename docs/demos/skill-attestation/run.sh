#!/usr/bin/env bash
# Gate-only skill-attestation demo driver — RUN THIS ON THE HOST (not inside a
# sandboxed session): it needs a reachable podman machine + Kind.
#
# Recreates the tamper-evident core of the weather-agent skill-attestation demo
# (design: SPIFFE Workload Identity–Bound Agent Skill Integrity, R. Chang et al.),
# minus the cosign/Rekor signing steps (those need RHTAS/Sigstore).
#
# Subcommands:
#   ./run.sh up        — kind cluster, build+load agent image, compute+pin digest, deploy, wait Ready
#   ./run.sh tamper     — modify a skill file, roll out, show the gate blocking the pod (Init:Error)
#   ./run.sh restore    — revert the skill file, roll out, show the gate passing again
#   ./run.sh logs       — dump the skill-integrity-gate init-container logs
#   ./run.sh down        — delete the kind cluster
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER="skill-demo"
NS="team1"
IMG="localhost/weather-service:demo"
GATE_IMG="ghcr.io/webchang/skill-hash:0.1.0"
ENGINE="${ENGINE:-podman}"        # podman | docker

# The skill collection is NOT vendored into this repo (it would duplicate
# agent-examples and get pulled into repo-wide linting). Instead we export it
# fresh from the canonical source at run time — exactly as the design PDF does:
#   git -C agent-examples archive HEAD:a2a/weather_service | tar -x
# Point AGENT_EXAMPLES at your local agent-examples clone.
AGENT_EXAMPLES="${AGENT_EXAMPLES:-$HERE/../../../../agent-examples}"
SKILLS_DIR="$HERE/.skills"        # gitignored working copy, populated by prepare_skills

# Kind needs to be told to use the podman provider (harmless for docker).
if [ "$ENGINE" = "podman" ]; then export KIND_EXPERIMENTAL_PROVIDER=podman; fi

# Side-load an image into the Kind node via a saved archive — works for both
# podman and docker, unlike `kind load docker-image` (docker store only).
load_into_kind() {
  local img="$1" tar="/tmp/kind-load-$$.tar"
  "$ENGINE" save "$img" -o "$tar"
  kind load image-archive "$tar" --name "$CLUSTER"
  rm -f "$tar"
}

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

require_engine() {
  if ! "$ENGINE" version >/dev/null 2>&1; then
    echo "ERROR: '$ENGINE' engine not reachable. Start it (e.g. 'podman machine start') and retry." >&2
    exit 1
  fi
}

prepare_skills() {
  # Export the weather skill collection from the canonical agent-examples source
  # into a local, gitignored working copy the demo builds/hashes.
  [ -d "$AGENT_EXAMPLES/.git" ] || {
    echo "ERROR: agent-examples clone not found at $AGENT_EXAMPLES (set AGENT_EXAMPLES=)" >&2; exit 1; }
  rm -rf "$SKILLS_DIR"; mkdir -p "$SKILLS_DIR"
  git -C "$AGENT_EXAMPLES" archive HEAD:a2a/weather_service | tar -x -C "$SKILLS_DIR"
  echo "skills exported to $SKILLS_DIR"
}

compute_digest() {
  # Compute the trusted digest by running the REAL skill-hash image against the
  # exported skill files — no reimplementation in the trust path.
  "$ENGINE" run --rm -v "$SKILLS_DIR:/skills:ro" -w /skills "$GATE_IMG" \
    compute --root /skills README.md,Dockerfile,src/weather_service/
}

cmd_up() {
  require_engine
  log "Pull gate image ($GATE_IMG)"
  "$ENGINE" pull "$GATE_IMG"

  log "Export weather skill collection from agent-examples"
  prepare_skills

  log "Compute trusted skill-collection digest (via real skill-hash image)"
  DIGEST="$(compute_digest | tr -d '[:space:]')"
  echo "trusted digest = $DIGEST"
  [ -n "$DIGEST" ] || { echo "empty digest — aborting"; exit 1; }

  log "Build stand-in agent image ($IMG) with skills baked at /app"
  "$ENGINE" build -f "$HERE/Dockerfile.agent" -t "$IMG" "$SKILLS_DIR"

  log "Create Kind cluster ($CLUSTER)"
  kind get clusters 2>/dev/null | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER"

  log "Load images into Kind (agent is localhost/ so must be side-loaded)"
  load_into_kind "$IMG"
  load_into_kind "$GATE_IMG"

  log "Render deployment with pinned digest and apply"
  kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
  sed "s|__SKILL_DIGEST__|$DIGEST|g" "$HERE/deployment.yaml.tmpl" | kubectl apply -f -

  log "Wait for the agent to become Ready (gate must pass first)"
  kubectl -n "$NS" rollout status deploy/weather-service --timeout=120s
  kubectl -n "$NS" get pods -l app=weather-service
  echo
  echo "SUCCESS: gate passed, agent Running. Now try: ./run.sh tamper"
}

cmd_tamper() {
  require_engine
  [ -d "$SKILLS_DIR" ] || { echo "run './run.sh up' first"; exit 1; }
  log "Tamper: append a line to a skill file (simulates skill modification)"
  echo "# TAMPERED $(date -u +%FT%TZ)" >> "$SKILLS_DIR/src/weather_service/agent.py"
  log "Rebuild + reload the agent image (skills baked in change => digest changes)"
  "$ENGINE" build -f "$HERE/Dockerfile.agent" -t "$IMG" "$SKILLS_DIR"
  load_into_kind "$IMG"
  log "Restart the pod — the PINNED digest is unchanged, so the gate must now FAIL"
  kubectl -n "$NS" rollout restart deploy/weather-service
  echo "Watching for Init:Error (Ctrl-C once you see it)..."
  echo "  kubectl -n $NS get pods -l app=weather-service -w"
  sleep 8
  kubectl -n "$NS" get pods -l app=weather-service
  echo
  echo "Expect: new pod stuck in Init:Error / CrashLoopBackOff on skill-integrity-gate."
  echo "The OLD pod stays Running (rolling update) — no outage. See ./run.sh logs"
}

cmd_restore() {
  require_engine
  log "Restore: re-export the pristine skill file from agent-examples"
  prepare_skills
  "$ENGINE" build -f "$HERE/Dockerfile.agent" -t "$IMG" "$SKILLS_DIR"
  load_into_kind "$IMG"
  kubectl -n "$NS" rollout restart deploy/weather-service
  kubectl -n "$NS" rollout status deploy/weather-service --timeout=120s
  echo "RESTORED: gate passes again, agent Running."
}

cmd_logs() {
  POD="$(kubectl -n "$NS" get pods -l app=weather-service \
        --sort-by=.metadata.creationTimestamp -o name | tail -1)"
  log "skill-integrity-gate logs for $POD"
  kubectl -n "$NS" logs "$POD" -c skill-integrity-gate || true
}

cmd_down() { kind delete cluster --name "$CLUSTER"; }

case "${1:-}" in
  up) cmd_up ;;
  tamper) cmd_tamper ;;
  restore) cmd_restore ;;
  logs) cmd_logs ;;
  down) cmd_down ;;
  *) echo "usage: $0 {up|tamper|restore|logs|down}"; exit 2 ;;
esac
