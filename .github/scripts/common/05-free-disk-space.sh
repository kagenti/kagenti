#!/usr/bin/env bash
# Free up disk space (Wave 05)
# Removes unnecessary packages and files in CI to prevent "no space left" errors

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/env-detect.sh"
source "$SCRIPT_DIR/../lib/logging.sh"

log_step "05" "Freeing up disk space"

if [ "$IS_CI" != true ]; then
    log_info "Skipping disk cleanup (not in CI)"
    exit 0
fi

log_info "Disk space before cleanup:"
df -h /

# Remove unnecessary packages
log_info "Removing unnecessary packages..."
sudo apt-get autoremove -y || log_warn "apt-get autoremove failed"
sudo apt-get clean || log_warn "apt-get clean failed"

# Remove Docker cache and unused images
log_info "Cleaning Docker resources..."
docker system prune -af --volumes || log_warn "Docker cleanup failed"

# Remove large packages we don't need in CI
log_info "Removing large unused packages..."
sudo rm -rf /usr/share/dotnet || true
sudo rm -rf /usr/local/lib/android || true
sudo rm -rf /opt/ghc || true
sudo rm -rf /opt/hostedtoolcache/CodeQL || true

log_info "Disk space after cleanup:"
df -h /

log_success "Disk space freed"
