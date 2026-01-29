#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

# Toolhive CRDs are no longer required. Tools are deployed as standard
# Kubernetes Deployments/StatefulSets + Services instead of MCPServer CRDs.
#
# This script is kept as a no-op for backward compatibility with workflows
# that still reference it.

log_step "43" "Toolhive CRDs no longer required (tools use Deployments)"
log_success "Skipped (tools now use standard Kubernetes workloads)"
