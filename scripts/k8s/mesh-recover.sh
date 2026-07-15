#!/usr/bin/env bash
#
# mesh-recover.sh — detect and (optionally) recover from an Istio Ambient
# mesh outage where ztunnel / waypoint proxies serve EXPIRED mTLS certificates
# and never re-fetch, so every gateway-routed service returns HTTP 503.
#
# This is the classic "long-running / suspended dev Kind cluster" failure
# (kagenti/kagenti#1899): a host suspend expires the istiod-issued workload
# certs, the Ambient data plane keeps serving them, and all *.localtest.me URLs
# 503 while every pod still looks Running. The durable fix is upstream
# (istio/ztunnel#1679); this script is the kagenti-side detect + recover
# mitigation for dev/Kind clusters.
#
# Read-only by default: it DETECTS and prints the recommended recovery
# commands. Pass --fix to actually run the rollout restarts.
#
# Scope: dev / Kind. Do not wire this to auto-run against production meshes.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Logging + command wrapper (self-contained; mirrors scripts/kind/setup-kagenti.sh
# so this file can be dropped into a container unchanged by the follow-up
# CronJob remediator — no external lib sourcing).
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'; NC=$'\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi
FIX=false
INCLUDE_SPIRE=false
JSON=false
# In --json mode all human logs go to stderr so stdout stays pure JSON
# (the follow-up CronJob remediator parses stdout).
log_info()    { if $JSON; then echo "→ $1" >&2; else echo "${BLUE}→${NC} $1"; fi; }
log_success() { if $JSON; then echo "✓ $1" >&2; else echo "${GREEN}✓${NC} $1"; fi; }
log_warn()    { if $JSON; then echo "⚠ $1" >&2; else echo "${YELLOW}⚠${NC} $1"; fi; }
log_error()   { echo "${RED}✗${NC} $1" >&2; }
PROBE_HOST=""
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
GW_NS="kagenti-system"
TIMEOUT=5

usage() {
  cat <<'EOF'
mesh-recover.sh — detect / recover an Istio Ambient mesh 503 outage (expired certs)

Usage: mesh-recover.sh [--fix] [--include-spire] [--probe-host HOST]
                       [--gateway-url URL] [--json] [-h]

  --fix            Perform recovery (rollout restart ztunnel + waypoints + gateway).
                   Default is DETECT-ONLY: report status and print the commands.
  --include-spire  Also check (and with --fix, restart) the SPIRE agent. This is a
                   SEPARATE failure domain (AuthBridge/token-exchange identity), not
                   the cause of the mesh 503 — off by default.
  --probe-host H   Host header to probe (e.g. kagenti-ui.localtest.me). Default:
                   auto-discovered from the http Gateway's routes.
  --gateway-url U  Gateway base URL to curl. Default: http://127.0.0.1:8080
                   (the Kind port-map; env GATEWAY_URL also honored).
  --json           Emit a machine-readable JSON summary (for the CronJob remediator).
  -h, --help       This help.

Exit: 0 healthy · 2 degraded (recoverable) · 3 inconclusive (unreachable / not Ambient) · 1 usage error.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix)           FIX=true; shift ;;
    --include-spire) INCLUDE_SPIRE=true; shift ;;
    --json)          JSON=true; shift ;;
    --probe-host)    PROBE_HOST="${2:-}"; shift 2 ;;
    --gateway-url)   GATEWAY_URL="${2:-}"; shift 2 ;;
    -h|--help)       usage; exit 0 ;;
    *) log_error "unknown argument: $1"; usage; exit 1 ;;
  esac
done

# run_cmd: gate mutating actions behind --fix (dry-run prints the command).
run_cmd() {
  if $FIX; then
    "$@"
  else
    echo "    [would run] $*"
  fi
}

command -v kubectl >/dev/null 2>&1 || { log_error "kubectl not found in PATH"; exit 1; }
HAVE_ISTIOCTL=false
command -v istioctl >/dev/null 2>&1 && HAVE_ISTIOCTL=true

# Findings accumulate here for the summary / JSON output.
DEGRADED=false       # a recoverable mesh outage (503 / expired certs) → exit 2, restart helps
INCONCLUSIVE=false   # can't confirm health (gateway unreachable, no ztunnel) → exit 3, restart won't help
declare -a CHECKS=()   # "name|status|detail"
declare -a ACTIONS=()  # recovery commands that were (or would be) run
record() {
  CHECKS+=("$1|$2|$3")
  case "$2" in
    DEGRADED)     DEGRADED=true ;;
    INCONCLUSIVE) INCONCLUSIVE=true ;;
  esac
  return 0
}

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
discover_ztunnel_ns() {
  # ztunnel namespace is NOT fixed: charts use istio-ztunnel, a plain istioctl
  # install uses istio-system. Discover by the daemonset's app=ztunnel label.
  local ns
  ns=$(kubectl get ds -A -l app=ztunnel -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null || true)
  [[ -z "$ns" ]] && for c in istio-system istio-ztunnel; do
    kubectl get ds -n "$c" ztunnel >/dev/null 2>&1 && { ns="$c"; break; }
  done
  echo "$ns"
}

discover_probe_host() {
  # Pick a BACKEND-DEPENDENT route: some routes (e.g. kiali) redirect (302) at the
  # gateway edge before the ztunnel->backend mTLS hop, so they stay 302 even during
  # a mesh outage and would give a false-healthy. Prefer the platform UI/API routes
  # in kagenti-system, which return a backend response (200) and flip to 503 when the
  # mesh is broken.
  [[ -n "$PROBE_HOST" ]] && { echo "$PROBE_HOST"; return; }
  local h
  h=$(kubectl get httproute -n "$GW_NS" -o jsonpath='{range .items[*]}{.spec.hostnames[0]}{"\n"}{end}' 2>/dev/null \
      | grep -m1 -E 'kagenti-ui|kagenti-api' || true)
  [[ -z "$h" ]] && h=$(kubectl get httproute -n "$GW_NS" -o jsonpath='{.items[0].spec.hostnames[0]}' 2>/dev/null || true)
  [[ -z "$h" ]] && h=$(kubectl get httproute -A -o jsonpath='{range .items[*]}{.spec.hostnames[0]}{"\n"}{end}' 2>/dev/null | grep -m1 'localtest.me' || true)
  echo "${h:-kagenti-ui.localtest.me}"
}

# ---------------------------------------------------------------------------
# Detectors (read-only)
# ---------------------------------------------------------------------------
check_mesh_reachability() {
  local host code body
  host=$(discover_probe_host)
  log_info "Probing gateway ${GATEWAY_URL} (Host: ${host}) ..."
  code=$(curl -s -o /dev/null -w '%{http_code}' -m "$TIMEOUT" -H "Host: ${host}" "${GATEWAY_URL}/" 2>/dev/null || true)
  code=${code:-000}
  if [[ "$code" == "503" ]]; then
    body=$(curl -s -m "$TIMEOUT" -H "Host: ${host}" "${GATEWAY_URL}/" 2>/dev/null || true)
    if grep -qi 'connection termination\|upstream connect error' <<<"$body"; then
      record "mesh-reachability" "DEGRADED" "HTTP 503 (connection termination) for ${host} — Ambient upstream mTLS is failing"
      log_error "503 with upstream connection termination for ${host} — classic expired-cert mesh outage"
    else
      record "mesh-reachability" "DEGRADED" "HTTP 503 for ${host}"
      log_error "503 for ${host}"
    fi
  elif [[ "$code" == "000" ]]; then
    record "mesh-reachability" "INCONCLUSIVE" "could not connect to ${GATEWAY_URL} — is the Kind port-map / port-forward up?"
    log_warn "Gateway ${GATEWAY_URL} unreachable (curl 000) — that's a port-map/port-forward issue, not a mesh cert outage; a restart won't help."
  else
    record "mesh-reachability" "OK" "HTTP ${code} for ${host}"
    log_success "Gateway reachable — HTTP ${code} for ${host} (not 503)"
  fi
}

check_ztunnel_certs() {
  local ns pod hits
  ns=$(discover_ztunnel_ns)
  if [[ -z "$ns" ]]; then
    record "ztunnel-certs" "INCONCLUSIVE" "no ztunnel daemonset found (app=ztunnel)"
    log_warn "No ztunnel daemonset found — is this an Ambient cluster?"
    return
  fi
  log_info "Checking ztunnel certs in namespace ${ns} ..."
  hits=$(kubectl logs -n "$ns" -l app=ztunnel --tail=300 --since=2h 2>/dev/null \
         | grep -ciE 'certificate expired|CertificateExpired' || true)
  if [[ "${hits:-0}" -gt 0 ]]; then
    record "ztunnel-certs" "DEGRADED" "${hits} expired-certificate errors in ztunnel logs (ns ${ns})"
    log_error "ztunnel is logging expired-certificate errors (${hits} hits, ns ${ns})"
  else
    record "ztunnel-certs" "OK" "no expired-certificate errors in recent ztunnel logs (ns ${ns})"
    log_success "ztunnel logs clean of expired-cert errors (ns ${ns})"
  fi
  if $HAVE_ISTIOCTL; then
    pod=$(kubectl get pods -n "$ns" -l app=ztunnel -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$pod" ]] && istioctl ztunnel-config certificates "$pod" -n "$ns" 2>/dev/null | grep -qi 'Unavailable'; then
      record "ztunnel-cert-status" "DEGRADED" "istioctl reports Unavailable certs on ${pod}"
      log_error "istioctl ztunnel-config certificates: Unavailable certs on ${pod}"
    fi
  else
    log_info "istioctl not found — skipping ztunnel-config certificate inspection (log check still applies)"
  fi
}

check_spire_agent() {
  local ns restarts prev
  ns=$(kubectl get pods -A -l app=spire-agent -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null || true)
  [[ -z "$ns" ]] && ns="spire-system"
  if ! kubectl get pods -n "$ns" -l app=spire-agent >/dev/null 2>&1; then
    record "spire-agent" "INCONCLUSIVE" "no spire-agent pods found"
    log_warn "No spire-agent pods found (ns ${ns}) — skipping SPIRE check"
    return
  fi
  log_info "Checking SPIRE agent in namespace ${ns} (separate domain: AuthBridge identity) ..."
  restarts=$(kubectl get pods -n "$ns" -l app=spire-agent \
             -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{"\n"}{end}' 2>/dev/null \
             | sort -rn | head -1 || echo 0)
  prev=$(kubectl logs -n "$ns" -l app=spire-agent --previous --tail=40 2>/dev/null \
         | grep -ciE 'reattest|service account token has expired|Agent crashed' || true)
  if [[ "${prev:-0}" -gt 0 || "${restarts:-0}" -ge 3 ]]; then
    record "spire-agent" "DEGRADED" "reattest/expiry signatures or ${restarts} restarts (ns ${ns})"
    log_error "SPIRE agent shows reattest-deadlock signatures (restarts=${restarts}, ns ${ns})"
  else
    record "spire-agent" "OK" "spire-agent healthy (restarts=${restarts}, ns ${ns})"
    log_success "SPIRE agent healthy (ns ${ns})"
  fi
}

# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------
recover_mesh() {
  local ns gw
  ns=$(discover_ztunnel_ns)
  echo
  log_info "Recovery — restart the Ambient data plane so it re-fetches fresh certs:"

  if [[ -n "$ns" ]]; then
    ACTIONS+=("kubectl rollout restart daemonset/ztunnel -n ${ns}")
    run_cmd kubectl rollout restart daemonset/ztunnel -n "$ns"
  fi

  # Waypoints: mesh-managed deployments, any namespace.
  while IFS=$'\t' read -r wns wname; do
    [[ -z "$wname" ]] && continue
    ACTIONS+=("kubectl rollout restart deploy/${wname} -n ${wns}")
    run_cmd kubectl rollout restart deploy/"$wname" -n "$wns"
  done < <(kubectl get deploy -A -l gateway.networking.k8s.io/managed-by=istio.io-mesh-controller \
           -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)

  # Gateway deployment (Istio names it <gateway>-istio, selected by gateway-name).
  gw=$(kubectl get deploy -n "$GW_NS" -l gateway.networking.k8s.io/gateway-name=http \
       -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  gw="${gw:-http-istio}"
  ACTIONS+=("kubectl rollout restart deploy/${gw} -n ${GW_NS}")
  run_cmd kubectl rollout restart deploy/"$gw" -n "$GW_NS"

  if $INCLUDE_SPIRE; then
    local sns
    sns=$(kubectl get pods -A -l app=spire-agent -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null || echo spire-system)
    ACTIONS+=("kubectl rollout restart daemonset/spire-agent -n ${sns}")
    run_cmd kubectl rollout restart daemonset/spire-agent -n "$sns"
  fi

  if $FIX; then
    log_info "Waiting for the data plane to settle ..."
    [[ -n "$ns" ]] && kubectl rollout status daemonset/ztunnel -n "$ns" --timeout=120s || true
    kubectl rollout status deploy/"$gw" -n "$GW_NS" --timeout=120s || true
    log_info "Re-probing to verify recovery ..."
    DEGRADED=false; INCONCLUSIVE=false; CHECKS=()
    check_mesh_reachability
  fi
}

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
emit_json() {
  local first=true
  printf '{"degraded":%s,"inconclusive":%s,"fixed":%s,"checks":[' "$DEGRADED" "$INCONCLUSIVE" "$FIX"
  for c in "${CHECKS[@]}"; do
    IFS='|' read -r n s d <<<"$c"
    $first || printf ','; first=false
    printf '{"name":"%s","status":"%s","detail":"%s"}' "$n" "$s" "${d//\"/\'}"
  done
  printf '],"actions":['
  first=true
  for a in "${ACTIONS[@]:-}"; do
    [[ -z "$a" ]] && continue
    $first || printf ','; first=false
    printf '"%s"' "$a"
  done
  printf ']}\n'
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
$JSON || { echo; log_info "Istio Ambient mesh self-heal — $($FIX && echo 'RECOVER (--fix)' || echo 'detect only') · scope: dev/Kind"; echo; }

check_mesh_reachability
check_ztunnel_certs
$INCLUDE_SPIRE && check_spire_agent

if $DEGRADED; then
  recover_mesh
fi

if $JSON; then
  emit_json
else
  echo
  if $DEGRADED && ! $FIX; then
    log_warn "Mesh looks degraded. Re-run with --fix to apply the recovery above, or run those commands manually."
    log_info "Root cause is upstream (istio/ztunnel#1679); this restart is the dev-cluster mitigation for #1899."
  elif $DEGRADED && $FIX; then
    log_success "Recovery applied — see re-probe result above."
  elif $INCONCLUSIVE; then
    log_warn "Could not confirm mesh health (gateway unreachable, or no ztunnel found). Check the gateway port-map and that this is an Ambient cluster — no restart attempted."
  else
    log_success "Mesh healthy — no action needed."
  fi
fi

if $DEGRADED; then exit 2; elif $INCONCLUSIVE; then exit 3; else exit 0; fi
