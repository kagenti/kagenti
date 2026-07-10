#!/usr/bin/env bash
#
# induce-mesh-outage.sh — repeatable test harness for mesh-recover.sh.
#
# The real #1899 outage (suspend/clock-jump expires the istiod-issued workload
# certs and the Ambient data plane keeps serving them) cannot be forced
# deterministically on Kind. This helper reproduces the SAME operator-visible
# symptom the reliable way: it makes the CA (istiod) unavailable and restarts
# ztunnel, so the data plane comes up WITHOUT a valid workload cert → every
# gateway route returns HTTP 503 (upstream connection termination), exactly like
# the expired-cert case. Recovery is identical: restart the data plane once the
# CA is healthy again — which is what `mesh-recover.sh --fix` does.
#
# It is a SYMPTOM reproduction, not a literal cert-expiry, and it is
# DESTRUCTIVE to the mesh for the duration. DEV / KIND ONLY.
#
#   induce-mesh-outage.sh --break        # induce the outage, leave it broken
#   induce-mesh-outage.sh --restore      # undo (scale istiod back, restart ztunnel)
#   induce-mesh-outage.sh --self-test    # break → assert detect → restore CA → --fix → assert green
#
set -euo pipefail

if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
else RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''; fi
log_info()    { echo "${BLUE}→${NC} $1"; }
log_success() { echo "${GREEN}✓${NC} $1"; }
log_warn()    { echo "${YELLOW}⚠${NC} $1"; }
log_error()   { echo "${RED}✗${NC} $1" >&2; }

MODE=""
FORCE=false
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
ISTIOD_NS="istio-system"
STATE_DIR="/tmp/kagenti/mesh-test"
STATE_FILE="${STATE_DIR}/istiod-replicas"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECOVER="${HERE}/mesh-recover.sh"

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//; 1d'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --break)     MODE=break; shift ;;
    --restore)   MODE=restore; shift ;;
    --self-test) MODE=selftest; shift ;;
    --force)     FORCE=true; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) log_error "unknown argument: $1"; usage; exit 1 ;;
  esac
done
[[ -z "$MODE" ]] && { log_error "one of --break | --restore | --self-test is required"; usage; exit 1; }

command -v kubectl >/dev/null 2>&1 || { log_error "kubectl not found"; exit 1; }

# Safety: dev/Kind only unless explicitly forced.
CTX="$(kubectl config current-context 2>/dev/null || echo '')"
if [[ "$CTX" != kind-* ]] && ! $FORCE; then
  log_error "current context '${CTX}' is not a Kind cluster. This tool is DESTRUCTIVE to the mesh."
  log_error "Refusing to run outside Kind. Re-run with --force only if you are certain (dev only)."
  exit 1
fi

mkdir -p "$STATE_DIR"

# ---- discovery ----
istiod_deploy() { kubectl get deploy -n "$ISTIOD_NS" -l app=istiod -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo istiod; }
ztunnel_ns()    { kubectl get ds -A -l app=ztunnel -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null || echo istio-system; }
probe_host() {
  # Backend-dependent route (see mesh-recover.sh) — kiali-style edge redirects hide outages.
  local h
  h=$(kubectl get httproute -n kagenti-system -o jsonpath='{range .items[*]}{.spec.hostnames[0]}{"\n"}{end}' 2>/dev/null | grep -m1 -E 'kagenti-ui|kagenti-api' || true)
  echo "${h:-kagenti-ui.localtest.me}"
}
probe_code()    { curl -s -o /dev/null -w '%{http_code}' -m 5 -H "Host: $(probe_host)" "${GATEWAY_URL}/" 2>/dev/null || echo 000; }

# Wait until the probe returns $1 (or "not-$1"); up to ~$2 seconds.
wait_for_code() {
  local want="$1" secs="${2:-60}" i code
  for ((i=0; i<secs; i+=3)); do
    code="$(probe_code)"
    if [[ "$want" == "503" && "$code" == "503" ]]; then return 0; fi
    if [[ "$want" == "healthy" && "$code" != "503" && "$code" != "000" ]]; then return 0; fi
    sleep 3
  done
  return 1
}

break_mesh() {
  local id ztns reps
  id="$(istiod_deploy)"; ztns="$(ztunnel_ns)"
  reps="$(kubectl get deploy -n "$ISTIOD_NS" "$id" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 1)"
  echo "${reps:-1}" > "$STATE_FILE"
  log_warn "Inducing mesh outage (DEV/KIND, context ${CTX}) — CA down + ztunnel restarted"
  log_info "scale deploy/${id} -n ${ISTIOD_NS} --replicas=0 (saved original=${reps:-1})"
  kubectl scale deploy/"$id" -n "$ISTIOD_NS" --replicas=0
  kubectl rollout status deploy/"$id" -n "$ISTIOD_NS" --timeout=60s 2>/dev/null || true
  # Hard-delete (not rollout restart): a graceful DaemonSet rollout keeps the old
  # cert-holding pod until the new one is Ready, so the mesh never breaks. Deleting
  # removes the cert holder; the recreated pod can't fetch a cert while the CA is down.
  log_info "force-delete ztunnel pods -n ${ztns} (recreated pods have no cert while CA is down)"
  kubectl delete pod -n "$ztns" -l app=ztunnel --force --grace-period=0 2>/dev/null || true
  log_info "waiting for gateway to return 503 ..."
  if wait_for_code 503 90; then
    log_success "outage induced — gateway now returns 503"
  else
    log_warn "did not observe a 503 within timeout (ztunnel may still hold a valid cert). Current code: $(probe_code)"
  fi
}

restore_mesh() {
  local id ztns reps
  id="$(istiod_deploy)"; ztns="$(ztunnel_ns)"
  reps="$(cat "$STATE_FILE" 2>/dev/null || echo 1)"; [[ "$reps" =~ ^[0-9]+$ ]] || reps=1
  log_info "restore: scale deploy/${id} -n ${ISTIOD_NS} --replicas=${reps}"
  kubectl scale deploy/"$id" -n "$ISTIOD_NS" --replicas="$reps"
  kubectl rollout status deploy/"$id" -n "$ISTIOD_NS" --timeout=90s 2>/dev/null || true
  log_info "restore: rollout restart daemonset/ztunnel -n ${ztns} (fetch fresh certs from healthy CA)"
  kubectl rollout restart daemonset/ztunnel -n "$ztns"
  kubectl rollout status daemonset/ztunnel -n "$ztns" --timeout=90s 2>/dev/null || true
  rm -f "$STATE_FILE"
  log_success "restore complete — final gateway code: $(probe_code)"
}

self_test() {
  local rc pass=true
  # Always put istiod back, even on failure/interrupt.
  trap 'echo; log_info "cleanup: ensuring istiod is restored"; restore_mesh >/dev/null 2>&1 || true' EXIT

  echo; log_info "=== 1) induce outage ==="; break_mesh

  echo; log_info "=== 2) detector must flag it (expect exit 2) ==="
  rc=0; "$RECOVER" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" == "2" ]]; then log_success "detector reported degraded (exit 2)"; else log_error "detector exit=${rc} (expected 2)"; pass=false; fi

  echo; log_info "=== 3) restore CA, then recover the data plane via --fix ==="
  local id; id="$(istiod_deploy)"
  kubectl scale deploy/"$id" -n "$ISTIOD_NS" --replicas="$(cat "$STATE_FILE" 2>/dev/null || echo 1)"
  kubectl rollout status deploy/"$id" -n "$ISTIOD_NS" --timeout=90s 2>/dev/null || true
  rc=0; "$RECOVER" --fix >/dev/null 2>&1 || rc=$?
  log_info "mesh-recover.sh --fix exit=${rc}"

  echo; log_info "=== 4) verify the mesh is healthy again (expect exit 0) ==="
  if wait_for_code healthy 90; then rc=0; "$RECOVER" >/dev/null 2>&1 || rc=$?; else rc=99; fi
  if [[ "$rc" == "0" ]]; then log_success "mesh healthy after recovery (exit 0)"; else log_error "mesh still degraded after --fix (probe=$(probe_code))"; pass=false; fi

  echo
  if $pass; then log_success "SELF-TEST PASSED"; else log_error "SELF-TEST FAILED"; fi
  $pass
}

case "$MODE" in
  break)    break_mesh ;;
  restore)  restore_mesh ;;
  selftest) self_test ;;
esac
