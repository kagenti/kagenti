#!/usr/bin/env bash
# Create Secrets for Bash Installer (Wave 20)
# Writes charts/kagenti/.secrets.yaml in Helm values format.
# Used by scripts/kind/setup-kagenti.sh (auto-detected via .secrets.yaml).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "20" "Creating secrets for bash installer"

SECRET_FILE="$REPO_ROOT/charts/kagenti/.secrets.yaml"

if [ -f "$SECRET_FILE" ]; then
    log_info "Secrets file already exists at $SECRET_FILE, skipping"
    exit 0
fi

OPENAI_KEY="${OPENAI_API_KEY:-ci-test-openai-key}"

cat > "$SECRET_FILE" <<EOF
secrets:
  githubUser: "ci-test-user"
  githubToken: "ci-test-token"
  openaiApiKey: "${OPENAI_KEY}"
  slackBotToken: "ci-test-slack-token"
  adminSlackBotToken: "ci-test-admin-slack-token"
EOF

log_success "Secrets created at $SECRET_FILE"
