#!/usr/bin/env bash
# Create Secrets (Wave 20)
# Creates .secret_values.yaml for Ansible

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "20" "Creating secret values"

# Use MAIN_REPO_ROOT for secrets (worktree-aware - secrets stay in main repo)
SECRET_FILE="$MAIN_REPO_ROOT/deployments/envs/.secret_values.yaml"

# Check if secrets already exist (in main repo)
if [ -f "$SECRET_FILE" ]; then
    log_info "Secrets file already exists at $SECRET_FILE, skipping"
    exit 0
fi

# Create directory in main repo (not worktree)
mkdir -p "$MAIN_REPO_ROOT/deployments/envs"

if [ "$IS_CI" = true ]; then
    log_info "Creating CI test secrets"
    cat > "$SECRET_FILE" <<EOF
# CI secret values (fake values for testing)
global:
  jwt_key: "ci-test-jwt-key"
  db_password: "ci-test-db-password"

kagenti:
  postgres:
    password: "ci-test-pg-password"

secrets:
  githubUser: "ci-test-user"
  githubToken: "ci-test-token"
  openaiApiKey: "ci-test-openai-key"
  slackBotToken: "ci-test-slack-token"
  adminSlackBotToken: "ci-test-admin-slack-token"
EOF
else
    log_info "Creating local test secrets"
    cat > "$SECRET_FILE" <<EOF
# Local secret values (for testing)
global:
  jwt_key: "local-test-jwt-key"
  db_password: "local-test-db-password"

kagenti:
  postgres:
    password: "local-test-pg-password"
EOF
fi

log_success "Secret values created"
