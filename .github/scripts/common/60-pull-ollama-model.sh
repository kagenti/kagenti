#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"
source "$SCRIPT_DIR/../lib/k8s-utils.sh"

log_step "60" "Pulling Ollama model"

# Log file for Ollama (only created if we start it)
OLLAMA_LOG="/tmp/ollama-$(date +%s).log"
STARTED_OLLAMA=false

# Stop any systemd service that might interfere (Ollama install script may enable it)
if systemctl is-active --quiet ollama 2>/dev/null; then
    log_info "Stopping Ollama systemd service"
    sudo systemctl stop ollama || true
fi

# Check if Ollama process is running
if pgrep -x "ollama" > /dev/null; then
    log_info "Ollama process already running, checking if responsive..."
else
    log_info "Starting Ollama in background"
    # Start Ollama with OLLAMA_HOST=0.0.0.0 to listen on all interfaces
    # This is required for Kind clusters to access Ollama from inside the Docker VM
    OLLAMA_HOST=0.0.0.0 ollama serve > "$OLLAMA_LOG" 2>&1 &
    STARTED_OLLAMA=true
fi

# Wait for Ollama to be responsive (whether we started it or it was already running)
log_info "Waiting for Ollama to be responsive..."
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        log_success "Ollama is responsive"
        break
    fi

    if [ $i -eq $MAX_WAIT ]; then
        log_error "Ollama failed to become responsive after ${MAX_WAIT} attempts (${i}s wait)"

        # Show logs if we started Ollama and log file exists
        if [ "$STARTED_OLLAMA" = true ] && [ -f "$OLLAMA_LOG" ]; then
            log_error "Ollama logs:"
            cat "$OLLAMA_LOG"
        fi

        # Show process info for debugging
        log_error "Ollama process info:"
        pgrep -a ollama || echo "No ollama process found"

        # Show port usage for debugging
        log_error "Port 11434 status:"
        netstat -tlnp 2>/dev/null | grep 11434 || echo "Port 11434 not in use"

        # Try to get version info
        log_error "Ollama version check:"
        ollama --version || echo "Failed to get ollama version"

        exit 1
    fi

    # Log progress every 10 seconds
    if [ $((i % 5)) -eq 0 ]; then
        log_info "Still waiting... (${i}/${MAX_WAIT})"
    fi

    sleep 2
done

# Pull model if not present with retry logic
if ! ollama list | grep -q qwen2.5:0.5b; then
    MAX_RETRIES=3
    RETRY_COUNT=0
    BACKOFF_SECONDS=10

    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        log_info "Pulling qwen2.5:0.5b model (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"

        if run_with_timeout 300 'ollama pull qwen2.5:0.5b'; then
            log_success "Model pull successful"
            break
        fi

        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            WAIT_TIME=$((BACKOFF_SECONDS * RETRY_COUNT))
            log_warn "Model pull failed - retrying in ${WAIT_TIME}s (attempt $RETRY_COUNT/$MAX_RETRIES)"
            sleep $WAIT_TIME
        else
            log_error "Model pull failed after $MAX_RETRIES attempts"
            exit 1
        fi
    done
fi

ollama list | grep qwen2.5 || {
    log_error "Model not found after pull"
    exit 1
}

log_success "Model ready"
