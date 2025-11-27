#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "42" "Applying pipeline template"

kubectl apply -f "$REPO_ROOT/kagenti/examples/agents/pipeline-template-dev.yaml"

log_success "Pipeline template applied"
