#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "30" "Running Ansible installer (Platform Operator)"

cd "$REPO_ROOT/deployments/ansible"
./run-install.sh --env dev

log_success "Ansible installer complete"
