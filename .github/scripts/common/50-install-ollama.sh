#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "50" "Installing Ollama"

if command -v ollama >/dev/null 2>&1; then
    log_info "Ollama already installed"
    exit 0
fi

# Download Ollama install script with retry logic for rate limiting
INSTALL_SCRIPT=$(mktemp)
trap 'rm -f "$INSTALL_SCRIPT"' EXIT

MAX_RETRIES=5
RETRY_COUNT=0
BACKOFF_SECONDS=5

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    log_info "Downloading Ollama install script (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"

    # Download and capture HTTP status code
    HTTP_CODE=$(curl -fsSL -w "%{http_code}" -o "$INSTALL_SCRIPT" https://ollama.com/install.sh 2>&1 | tail -n1 || echo "000")

    # Check if download succeeded
    if [ -s "$INSTALL_SCRIPT" ] && [ "$HTTP_CODE" = "200" ]; then
        log_success "Downloaded Ollama install script"
        break
    fi

    # Handle rate limiting (429) or server errors (5xx)
    if [[ "$HTTP_CODE" =~ ^(429|5[0-9][0-9])$ ]]; then
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            WAIT_TIME=$((BACKOFF_SECONDS * RETRY_COUNT))
            log_warn "HTTP $HTTP_CODE error - retrying in ${WAIT_TIME}s (attempt $RETRY_COUNT/$MAX_RETRIES)"
            sleep $WAIT_TIME
        else
            log_error "Failed after $MAX_RETRIES attempts (HTTP $HTTP_CODE)"
            exit 1
        fi
    else
        log_error "Download failed with HTTP code: $HTTP_CODE"
        exit 1
    fi
done

# Execute the install script with retry logic
# The Ollama install script downloads from GitHub which can have rate limiting
INSTALL_RETRY_COUNT=0
INSTALL_MAX_RETRIES=5
INSTALL_BACKOFF=10

while [ $INSTALL_RETRY_COUNT -lt $INSTALL_MAX_RETRIES ]; do
    log_info "Running Ollama install script (attempt $((INSTALL_RETRY_COUNT + 1))/$INSTALL_MAX_RETRIES)"

    if bash "$INSTALL_SCRIPT"; then
        log_success "Ollama installed"
        exit 0
    fi

    INSTALL_RETRY_COUNT=$((INSTALL_RETRY_COUNT + 1))
    if [ $INSTALL_RETRY_COUNT -lt $INSTALL_MAX_RETRIES ]; then
        WAIT_TIME=$((INSTALL_BACKOFF * INSTALL_RETRY_COUNT))
        log_warn "Ollama install failed - retrying in ${WAIT_TIME}s (attempt $INSTALL_RETRY_COUNT/$INSTALL_MAX_RETRIES)"
        sleep $WAIT_TIME
    else
        log_error "Ollama install failed after $INSTALL_MAX_RETRIES attempts"
        exit 1
    fi
done
