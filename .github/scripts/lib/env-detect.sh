#!/usr/bin/env bash
# shellcheck disable=SC2155
# SC2155: Declare and assign separately - safe here as assignments use fallback defaults
#
# Environment Detection Library
# Detects if running in CI or locally and sets environment variables

# Don't use set -euo pipefail in sourced library to avoid affecting parent shell

# Detect if running in CI
if [ -n "${GITHUB_ACTIONS:-}" ]; then
    export IS_CI=true
    export REPO_ROOT="${GITHUB_WORKSPACE}"
    export MAIN_REPO_ROOT="${GITHUB_WORKSPACE}"
    echo "Running in CI (GitHub Actions)"
else
    export IS_CI=false
    # Get script directory - handle both direct execution and sourcing
    if [ -n "${BASH_SOURCE[0]:-}" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        export REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
    else
        # Fallback: use git to find repo root
        export REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    fi
    echo "Running locally"

    # Detect if running from a git worktree - if so, find the main repo root
    # This is needed because files like .secret_values.yaml may only exist in main repo
    if [[ "$REPO_ROOT" == *"/.worktrees/"* ]]; then
        # Extract path before .worktrees - this is the main repo root
        export MAIN_REPO_ROOT="${REPO_ROOT%%/.worktrees/*}"
        echo "Detected worktree: using MAIN_REPO_ROOT=$MAIN_REPO_ROOT for shared files"
    else
        # Not a worktree - main repo root is same as repo root
        export MAIN_REPO_ROOT="$REPO_ROOT"
    fi
fi

# Detect if running on macOS or Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
    export IS_MACOS=true
    echo "Detected OS: macOS"
else
    export IS_MACOS=false
    echo "Detected OS: Linux"
fi

# Detect if running on OpenShift vs vanilla Kubernetes (Kind, etc.)
# NOTE: "oc whoami" works on ANY Kubernetes cluster - it just checks authentication!
# We must check for OpenShift-specific APIs to properly detect OpenShift.
if kubectl api-resources --api-group=build.openshift.io 2>/dev/null | grep -q "buildconfigs"; then
    export IS_OPENSHIFT=true
    echo "Detected cluster type: OpenShift"
else
    export IS_OPENSHIFT=false
    echo "Detected cluster type: Kubernetes (Kind/vanilla)"
fi

# Export for child scripts
export IS_CI
export IS_MACOS
export IS_OPENSHIFT
export REPO_ROOT
