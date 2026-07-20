#!/usr/bin/env bash
#
# Diagnose the agent -> MCP-tool egress path (issue #1904 / the DNS-drop in the
# enforce-redirect guard). Invoked by the agent-conversation e2e tests when the
# agent returns a FAILED "Cannot connect to MCP" task, so the run shows exactly
# what breaks vs what works instead of a bare "Cannot connect".
#
# It is read-only and best-effort: every command is guarded so it can never
# change the test outcome. Usage: diagnose_agent_mcp.sh [namespace]   (default team1)
#
# Borrows the DNS-isolation trick from PR #1909: probe the MCP tool by FQDN
# (needs cluster DNS) AND by ClusterIP (no DNS). If FQDN fails but ClusterIP is
# reached, DNS is the blocker; if both are reached, the path is healthy; if both
# fail, the break is at the connection/proxy layer, not DNS.
set +e

NS="${1:-team1}"
KUBECTL="${KUBECTL:-kubectl}"

echo "=================================================================="
echo "AGENT->MCP DIAGNOSTICS (namespace=${NS})"
echo "=================================================================="

# --- Locate the weather agent pod specifically (Deployment 'weather-service' on
#     OCP, Sandbox 'weather-agent' on Kind). Match by the weather label/name only
#     — never the generic rossoctl.io/type=agent (other agents share it). ---
POD=$(${KUBECTL} get pod -n "${NS}" -l "app.kubernetes.io/name=weather-service" \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -z "${POD}" ] && POD=$(${KUBECTL} get pods -n "${NS}" --no-headers 2>/dev/null \
  | awk '/^weather-(service|agent)/{print $1; exit}')
if [ -z "${POD}" ]; then
  echo "  no weather agent pod found in ${NS} — nothing to diagnose"
  exit 0
fi
echo "  agent pod: ${POD}"

# --- AuthBridge injection mode ---
INITS=$(${KUBECTL} get pod "${POD}" -n "${NS}" -o jsonpath='{.spec.initContainers[*].name}' 2>/dev/null)
CONTS=$(${KUBECTL} get pod "${POD}" -n "${NS}" -o jsonpath='{.spec.containers[*].name}' 2>/dev/null)
echo "  init=[${INITS}] containers=[${CONTS}]"
if echo "${INITS}" | grep -q proxy-init; then
  echo "  AuthBridge enforce-redirect ACTIVE (proxy-init present -> egress captured at L4)"
else
  echo "  no proxy-init (cooperative HTTP_PROXY mode, or AuthBridge not injected)"
fi

# --- proxy-init log: the DNS exemption it applied. The key line is either
#     'resolvers=<ip>' (resolv.conf-based fix) or 'CIDRs=<cidrs>' (old build). ---
echo "--- proxy-init log (DNS exemption applied) ---"
${KUBECTL} logs "${POD}" -n "${NS}" -c proxy-init 2>&1 \
  | grep -iE "enforce-redirect|resolver|CIDRs|WARNING|ERROR" || echo "  (no proxy-init log)"

# --- proxy-init env: CLUSTER_CIDRS should be ABSENT once the resolv.conf fix is
#     in (operator no longer injects it). Its presence means an old image/operator. ---
echo "--- proxy-init env ---"
${KUBECTL} get pod "${POD}" -n "${NS}" \
  -o jsonpath='{range .spec.initContainers[?(@.name=="proxy-init")].env[*]}    {.name}={.value}{"\n"}{end}' 2>/dev/null \
  || echo "  (could not read proxy-init env)"

# --- The agent's actual resolver(s) ---
echo "--- agent /etc/resolv.conf nameservers ---"
${KUBECTL} exec "${POD}" -n "${NS}" -c agent -- \
  sh -c 'grep "^nameserver" /etc/resolv.conf 2>/dev/null | sed "s/^/    /"' 2>&1 \
  || echo "  (exec failed)"

# --- DNS-isolation probe: FQDN (needs DNS) vs ClusterIP (no DNS), at the agent's
#     real MCP port ---
MCP_URL=$(${KUBECTL} get pod "${POD}" -n "${NS}" \
  -o jsonpath='{range .spec.containers[?(@.name=="agent")].env[?(@.name=="MCP_URL")].value}{@}{end}' 2>/dev/null)
[ -z "${MCP_URL}" ] && MCP_URL="http://weather-tool-mcp.${NS}.svc.cluster.local:8000/mcp"
MCP_PORT=$(printf '%s' "${MCP_URL}" | sed -E 's#^https?://[^/]*:([0-9]+).*#\1#'); echo "${MCP_PORT}" | grep -qE '^[0-9]+$' || MCP_PORT=80
MCP_SVC_IP=$(${KUBECTL} get svc weather-tool-mcp -n "${NS}" -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
echo "--- MCP reachability (MCP_URL=${MCP_URL}, ClusterIP=${MCP_SVC_IP:-<none>}, port=${MCP_PORT}) ---"

PYPROBE='
import sys, http.client, json
ns, port, svc_ip = sys.argv[1], int(sys.argv[2]), (sys.argv[3] if len(sys.argv) > 3 else "")
fqdn = "weather-tool-mcp.%s.svc.cluster.local" % ns
body = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"diag","version":"0"}}})
def probe(label, host, host_hdr=None):
    h = {"Content-Type":"application/json","Accept":"application/json, text/event-stream"}
    if host_hdr: h["Host"] = host_hdr
    try:
        c = http.client.HTTPConnection(host, port, timeout=12)
        c.request("POST", "/mcp", body, h)
        r = c.getresponse()
        print("    %-26s REACHED (status=%s, server responded)" % (label, r.status))
    except Exception as e:
        print("    %-26s FAIL: %s: %s" % (label, type(e).__name__, e))
probe("by FQDN (needs DNS)", fqdn)
if svc_ip:
    probe("by ClusterIP (no DNS)", svc_ip, host_hdr=fqdn)
print("    interpretation: FQDN-fail + ClusterIP-reached => DNS is the blocker;")
print("                    both reached => path healthy; both fail => proxy/connection layer.")
'
${KUBECTL} exec "${POD}" -n "${NS}" -c agent -- \
  python3 -c "${PYPROBE}" "${NS}" "${MCP_PORT}" "${MCP_SVC_IP}" 2>&1 \
  || echo "  (MCP probe exec failed)"

# --- AuthBridge proxy logs: did it see/forward the MCP call, or error? ---
AB=$(echo "${CONTS}" | tr ' ' '\n' | grep -E 'authbridge' | head -1)
if [ -n "${AB}" ]; then
  echo "--- authbridge proxy logs (${AB}, weather-tool/mcp/error lines, tail) ---"
  ${KUBECTL} logs "${POD}" -n "${NS}" -c "${AB}" --tail=80 2>&1 \
    | grep -iE "weather-tool|/mcp|passthrough|outbound|error|denied|503|502" | tail -25 \
    || echo "  (no matching authbridge log lines)"
fi

echo "=================================================================="
exit 0
