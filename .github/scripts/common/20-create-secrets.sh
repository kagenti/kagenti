#!/usr/bin/env bash
# Create Secrets (Wave 20)
# Creates .secrets.yaml for Helm-based installers

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "20" "Creating secret values"

# Use MAIN_REPO_ROOT for secrets (worktree-aware - secrets stay in main repo)
SECRET_FILE="$MAIN_REPO_ROOT/charts/kagenti/.secrets.yaml"

# Check if secrets already exist (in main repo)
if [ -f "$SECRET_FILE" ]; then
    log_info "Secrets file already exists at $SECRET_FILE, skipping"
    exit 0
fi

# Ensure chart directory exists in main repo
mkdir -p "$MAIN_REPO_ROOT/charts/kagenti"

if [ "$IS_CI" = true ]; then
    log_info "Creating CI test secrets"
    OPENAI_KEY="${OPENAI_API_KEY:-ci-test-openai-key}"
    cat > "$SECRET_FILE" <<EOF
secrets:
  githubUser: "ci-test-user"
  githubToken: "ci-test-token"
  openaiApiKey: "${OPENAI_KEY}"
  slackBotToken: "ci-test-slack-token"
  adminSlackBotToken: "ci-test-admin-slack-token"
EOF
else
    log_info "Creating local test secrets from template"
    if [ -f "$MAIN_REPO_ROOT/charts/kagenti/.secrets_template.yaml" ]; then
        cp "$MAIN_REPO_ROOT/charts/kagenti/.secrets_template.yaml" "$SECRET_FILE"
    else
        cat > "$SECRET_FILE" <<EOF
secrets:
  githubUser: ""
  githubToken: ""
  openaiApiKey: ""
  slackBotToken: ""
  adminSlackBotToken: ""
EOF
    fi
fi

log_success "Secret values created"
