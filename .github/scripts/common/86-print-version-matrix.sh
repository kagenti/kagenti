#!/usr/bin/env bash
# Print a collapsible version matrix of all deployed images and Helm releases.
# In GitHub Actions the output is wrapped in ::group:: / ::endgroup:: so it
# appears as a collapsed section in the job log.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "86" "Printing version matrix"

# Helper: print a section header
_section() {
    echo ""
    echo "=== $1 ==="
}

# Start collapsible group in GitHub Actions
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::group::Version Matrix — deployed images, Helm releases, cluster info"
fi

# -------------------------------------------------------------------------
# 1. Cluster information
# -------------------------------------------------------------------------
_section "Cluster"
echo "Kubernetes server: $(kubectl version --short 2>/dev/null | grep -i server || kubectl version -o json 2>/dev/null | python3 -c 'import sys,json; v=json.load(sys.stdin)["serverVersion"]; print(f"v{v[\"major\"]}.{v[\"minor\"]}")' 2>/dev/null || echo 'unknown')"
echo "Context: $(kubectl config current-context 2>/dev/null || echo 'unknown')"
if [ "$IS_OPENSHIFT" = "true" ]; then
    echo "OpenShift: $(oc version 2>/dev/null | head -2 || echo 'unknown')"
fi

# -------------------------------------------------------------------------
# 2. Helm releases
# -------------------------------------------------------------------------
_section "Helm Releases"
helm list -A --output table 2>/dev/null || echo "(helm not available)"

# -------------------------------------------------------------------------
# 3. Container images per namespace
# -------------------------------------------------------------------------
_section "Container Images"

for ns in kagenti-system keycloak team1 team2; do
    pods_json=$(kubectl get pods -n "$ns" -o json 2>/dev/null || echo '{"items":[]}')
    images=$(echo "$pods_json" | python3 -c '
import sys, json
data = json.load(sys.stdin)
seen = set()
for pod in data.get("items", []):
    for cs in pod.get("status", {}).get("containerStatuses", []):
        img = cs.get("image", "")
        if img and img not in seen:
            seen.add(img)
            print(img)
    for cs in pod.get("status", {}).get("initContainerStatuses", []):
        img = cs.get("image", "")
        if img and img not in seen:
            seen.add(img)
            print(img)
' 2>/dev/null | sort || true)

    if [ -n "$images" ]; then
        echo ""
        echo "--- $ns ---"
        echo "$images"
    fi
done

# -------------------------------------------------------------------------
# 4. Operator versions (if present)
# -------------------------------------------------------------------------
if kubectl get csv -n kagenti-system -o name 2>/dev/null | head -1 | grep -q .; then
    _section "Operator CSVs (kagenti-system)"
    kubectl get csv -n kagenti-system -o custom-columns=NAME:.metadata.name,VERSION:.spec.version,PHASE:.status.phase 2>/dev/null || true
fi

# End collapsible group
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::endgroup::"
fi

log_success "Version matrix printed"
