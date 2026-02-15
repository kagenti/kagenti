#!/usr/bin/env bash
#
# Run Playwright Tests with Video Recording
#
# Records video of Playwright E2E tests running against a live Kagenti cluster.
# Handles Keycloak authentication automatically.
# Optionally adds voiceover using OpenAI TTS.
#
# USAGE:
#   ./local_experiments/run-playwright-demo.sh [options]
#
# Without --test or --all, shows available tests and copy-pasteable commands (dry run).
#
# OPTIONS:
#   --cluster-suffix SUFFIX   HyperShift cluster suffix (e.g., ladas, pr529)
#   --repo-path PATH          Path to kagenti repo or worktree (default: auto-detect)
#   --kind                    Use Kind cluster instead of HyperShift
#   --test PREFIX             Run tests matching prefix (e.g., home, agent, tool)
#   --all                     Run all Playwright tests
#   -h, --help                Show this help message
#
# ENVIRONMENT:
#   KEYCLOAK_USER             Override Keycloak username (default: auto-discovered from cluster)
#   KEYCLOAK_PASS             Override Keycloak password (default: auto-discovered from cluster)
#   OPENAI_API_KEY            If set, adds voiceover to recorded videos
#   MANAGED_BY_TAG            HyperShift managed-by tag (default: kagenti-hypershift-custom)
#
# EXAMPLES:
#   # List available tests (dry run)
#   ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas
#
#   # Record specific test
#   ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --test home
#
#   # Record all tests
#   ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --all
#
#   # Run from a worktree
#   ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --repo-path .worktrees/my-feature --test agent
#
#   # Kind cluster
#   ./local_experiments/run-playwright-demo.sh --kind --test home

set -euo pipefail

# ============================================================================
# Colors
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}[info]${NC} $1"; }
log_success() { echo -e "${GREEN}[ok]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[warn]${NC} $1"; }
log_error()   { echo -e "${RED}[error]${NC} $1" >&2; }

# ============================================================================
# Script directory (where local_experiments/ lives)
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================================
# Parse arguments
# ============================================================================
CLUSTER_SUFFIX=""
REPO_PATH=""
USE_KIND=false
TEST_PREFIX=""
RUN_ALL=false
SHOW_HELP=false
NO_NARRATION=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            SHOW_HELP=true
            shift
            ;;
        --cluster-suffix)
            CLUSTER_SUFFIX="$2"
            shift 2
            ;;
        --repo-path)
            REPO_PATH="$2"
            shift 2
            ;;
        --kind)
            USE_KIND=true
            shift
            ;;
        --test)
            TEST_PREFIX="$2"
            shift 2
            ;;
        --all)
            RUN_ALL=true
            shift
            ;;
        --no-narration)
            NO_NARRATION=true
            shift
            ;;
        *)
            log_error "Unknown argument: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# ============================================================================
# Help
# ============================================================================
if [ "$SHOW_HELP" = true ]; then
    cat << 'EOF'
run-playwright-demo.sh - Record Playwright test videos against a live Kagenti cluster

USAGE:
    ./local_experiments/run-playwright-demo.sh [options]

    Without --test or --all, shows available tests and copy-pasteable commands.

OPTIONS:
    --cluster-suffix SUFFIX   HyperShift cluster suffix (e.g., ladas, pr529)
    --repo-path PATH          Path to kagenti repo or worktree (default: auto-detect)
    --kind                    Use Kind cluster instead of HyperShift
    --test PREFIX             Run tests matching prefix (e.g., home, agent, tool)
    --all                     Run all Playwright tests
    -h, --help                Show this help message

ENVIRONMENT VARIABLES:
    KEYCLOAK_USER             Override Keycloak username (auto-discovered if not set)
    KEYCLOAK_PASS             Override Keycloak password (auto-discovered if not set)
    OPENAI_API_KEY            If set, generates voiceover for recorded videos
    MANAGED_BY_TAG            HyperShift managed-by tag (default: kagenti-hypershift-custom)

EXAMPLES:
    # List available tests (dry run)
    ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas

    # Record the home page test
    ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --test home

    # Record all tests
    ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas --all

    # Run tests from a worktree
    ./local_experiments/run-playwright-demo.sh --cluster-suffix ladas \
        --repo-path .worktrees/my-feature --test agent

    # Kind cluster
    ./local_experiments/run-playwright-demo.sh --kind --test home

OUTPUT:
    Videos saved as: local_experiments/<test-name>_<YYYY-MM-DD_HH-MM>.webm
    With voiceover:  local_experiments/<test-name>_<YYYY-MM-DD_HH-MM>_voiceover.mp4
EOF
    exit 0
fi

# ============================================================================
# Resolve repo path
# ============================================================================
if [ -z "$REPO_PATH" ]; then
    REPO_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Make absolute
REPO_PATH="$(cd "$REPO_PATH" && pwd)"

UI_DIR="$REPO_PATH/kagenti/ui-v2"
E2E_DIR="$UI_DIR/e2e"

if [ ! -d "$E2E_DIR" ]; then
    log_error "E2E test directory not found: $E2E_DIR"
    log_error "Check --repo-path or ensure the kagenti repo structure is intact."
    exit 1
fi

# ============================================================================
# Discover available tests
# ============================================================================
LOCAL_E2E_DIR="$REPO_PATH/kagenti/ui-v2/e2e/demos"

DEMO_MAP="$SCRIPT_DIR/demo-map.json"

get_test_description() {
    if [ -f "$DEMO_MAP" ]; then
        local desc
        desc=$(python3 -c "import json; d=json.load(open('$DEMO_MAP')); print(d.get('$1',{}).get('description',''))" 2>/dev/null)
        if [ -n "$desc" ]; then
            echo "$desc"
            return
        fi
    fi
    # Fallback for tests not in demo-map.json
    case "$1" in
        home)              echo "Home page, navigation, sidebar" ;;
        agent-catalog)     echo "Agent listing, import, API integration" ;;
        tool-catalog)      echo "Tool listing, import, API integration" ;;
        *)                 echo "" ;;
    esac
}

# Get the output directory for a test from demo-map.json
get_demo_dir() {
    local test_name="$1"
    if [ -f "$DEMO_MAP" ]; then
        local dir
        dir=$(python3 -c "import json; d=json.load(open('$DEMO_MAP')); print(d.get('$test_name',{}).get('dir',''))" 2>/dev/null)
        if [ -n "$dir" ]; then
            echo "$SCRIPT_DIR/demos/$dir"
            return
        fi
    fi
    # Fallback: flat directory
    echo "$SCRIPT_DIR/demos/$test_name"
}

discover_tests() {
    # Tests from the repo's e2e directory
    for spec_file in "$E2E_DIR"/*.spec.ts; do
        if [ -f "$spec_file" ]; then
            basename "$spec_file" .spec.ts
        fi
    done
    # Tests from local_experiments/e2e
    for spec_file in "$LOCAL_E2E_DIR"/*.spec.ts; do
        if [ -f "$spec_file" ]; then
            basename "$spec_file" .spec.ts
        fi
    done
}

count_tests_in_file() {
    local file="$1"
    grep -c "test(" "$file" 2>/dev/null || echo "?"
}

AVAILABLE_TESTS=()
while IFS= read -r t; do
    AVAILABLE_TESTS+=("$t")
done < <(discover_tests)

# ============================================================================
# Discover UI URL from cluster
# ============================================================================
discover_ui_url() {
    if [ "$USE_KIND" = true ]; then
        echo "http://kagenti-ui.localtest.me:8080"
        return
    fi

    # HyperShift — need kubeconfig
    if [ -z "$CLUSTER_SUFFIX" ]; then
        log_error "HyperShift mode requires --cluster-suffix"
        exit 1
    fi

    local managed_by="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    local cluster_name="${managed_by}-${CLUSTER_SUFFIX}"
    local kubeconfig_path="$HOME/clusters/hcp/${cluster_name}/auth/kubeconfig"

    if [ ! -f "$kubeconfig_path" ]; then
        log_error "Kubeconfig not found: $kubeconfig_path"
        log_error "Create the cluster first or check --cluster-suffix"
        exit 1
    fi

    export KUBECONFIG="$kubeconfig_path"
    # Log to stderr so it doesn't contaminate the captured URL
    log_info "Using kubeconfig: $KUBECONFIG" >&2

    # Discover UI route
    local ui_host
    ui_host=$(oc get route -n kagenti-system kagenti-ui -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

    if [ -z "$ui_host" ]; then
        log_error "kagenti-ui route not found in cluster"
        log_error "Is Kagenti deployed? Run: oc get routes -n kagenti-system"
        exit 1
    fi

    echo "https://$ui_host"
}

# ============================================================================
# Discover Keycloak credentials from cluster
# ============================================================================
discover_keycloak_creds() {
    if [ -n "${KEYCLOAK_USER:-}" ] && [ -n "${KEYCLOAK_PASS:-}" ]; then
        log_info "Using Keycloak credentials from environment"
        return
    fi

    local cli="kubectl"
    if command -v oc &>/dev/null && [ "$USE_KIND" = false ]; then
        cli="oc"
    fi

    # Use explicit --kubeconfig to ensure we're querying the right cluster
    local kc_flag=""
    if [ -n "${KUBECONFIG:-}" ]; then
        kc_flag="--kubeconfig=$KUBECONFIG"
    fi

    # Try keycloak-initial-admin first (master admin, always has full access including kagenti-viewer role)
    # Fall back to kagenti-test-user (app user, may lack client roles on some clusters)
    local user pass
    user=$($cli $kc_flag get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    pass=$($cli $kc_flag get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

    if [ -n "$user" ] && [ -n "$pass" ]; then
        export KEYCLOAK_USER="$user"
        export KEYCLOAK_PASS="$pass"
        log_info "Discovered admin credentials from keycloak-initial-admin (user: $user)"
    else
        # Fall back to kagenti-test-user (app user in demo realm)
        user=$($cli $kc_flag get secret -n keycloak kagenti-test-user -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
        pass=$($cli $kc_flag get secret -n keycloak kagenti-test-user -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

        if [ -n "$user" ] && [ -n "$pass" ]; then
            export KEYCLOAK_USER="$user"
            export KEYCLOAK_PASS="$pass"
            export KEYCLOAK_CRED_SOURCE="kagenti-test-user"
            log_info "Discovered app credentials from kagenti-test-user (user: $user)"
        else
            export KEYCLOAK_USER="${KEYCLOAK_USER:-admin}"
            export KEYCLOAK_PASS="${KEYCLOAK_PASS:-admin}"
            log_warn "Could not discover Keycloak credentials, using defaults (admin/admin)"
        fi
    fi
}

# ============================================================================
# Build the --test or --all invocation command suffix for display
# ============================================================================
build_script_prefix() {
    local prefix="./local_experiments/run-playwright-demo.sh"
    if [ "$USE_KIND" = true ]; then
        prefix="$prefix --kind"
    elif [ -n "$CLUSTER_SUFFIX" ]; then
        prefix="$prefix --cluster-suffix $CLUSTER_SUFFIX"
    fi
    if [ -n "$REPO_PATH" ] && [ "$REPO_PATH" != "$(cd "$SCRIPT_DIR/.." && pwd)" ]; then
        prefix="$prefix --repo-path $REPO_PATH"
    fi
    echo "$prefix"
}

# ============================================================================
# DRY RUN — show available tests (default when no --test or --all)
# ============================================================================
if [ "$RUN_ALL" = false ] && [ -z "$TEST_PREFIX" ]; then
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}┃${NC} Playwright Demo Recorder — Available Tests"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Show cluster info if we can detect it
    if [ "$USE_KIND" = true ]; then
        UI_URL="http://kagenti-ui.localtest.me:8080"
        echo -e "  ${CYAN}Cluster:${NC} Kind"
        echo -e "  ${CYAN}UI URL:${NC}  $UI_URL"
        echo ""
    elif [ -n "$CLUSTER_SUFFIX" ]; then
        managed_by="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
        cluster_name="${managed_by}-${CLUSTER_SUFFIX}"
        kubeconfig_path="$HOME/clusters/hcp/${cluster_name}/auth/kubeconfig"
        echo -e "  ${CYAN}Cluster:${NC} $cluster_name"
        if [ -f "$kubeconfig_path" ]; then
            UI_URL=$(KUBECONFIG="$kubeconfig_path" oc get route -n kagenti-system kagenti-ui -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$UI_URL" ]; then
                echo -e "  ${CYAN}UI URL:${NC}  https://$UI_URL"
            else
                echo -e "  ${YELLOW}UI URL:${NC}  (route not found — is Kagenti deployed?)"
            fi
        else
            echo -e "  ${YELLOW}Kubeconfig:${NC} not found at $kubeconfig_path"
        fi
        echo ""
    fi

    echo -e "  ${CYAN}Repo:${NC}    $REPO_PATH"
    echo -e "  ${CYAN}Tests:${NC}   $E2E_DIR"
    echo ""

    # List tests
    local_i=1
    for test_name in "${AVAILABLE_TESTS[@]}"; do
        count=$(count_tests_in_file "$E2E_DIR/${test_name}.spec.ts")
        desc=$(get_test_description "$test_name")
        if [ -n "$desc" ]; then
            printf "  ${GREEN}%2d.${NC} %-20s (%s tests) - %s\n" "$local_i" "$test_name" "$count" "$desc"
        else
            printf "  ${GREEN}%2d.${NC} %-20s (%s tests)\n" "$local_i" "$test_name" "$count"
        fi
        local_i=$((local_i + 1))
    done

    echo ""
    echo -e "  ${YELLOW}Run a specific test:${NC}"
    CMD_PREFIX=$(build_script_prefix)
    for test_name in "${AVAILABLE_TESTS[@]}"; do
        echo "    $CMD_PREFIX --test $test_name"
    done

    echo ""
    echo -e "  ${YELLOW}Run all tests:${NC}"
    echo "    $CMD_PREFIX --all"

    echo ""
    if [ -n "${OPENAI_API_KEY:-}" ]; then
        echo -e "  ${GREEN}Voiceover:${NC} OPENAI_API_KEY is set — voiceover will be generated"
    else
        echo -e "  ${CYAN}Voiceover:${NC} Set OPENAI_API_KEY to add voiceover to recordings"
    fi
    echo ""
    exit 0
fi

# ============================================================================
# EXECUTION MODE — run tests with video recording
# ============================================================================

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}┃${NC} Playwright Demo Recorder"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Set KUBECONFIG for HyperShift clusters (must be done before subshell calls)
if [ "$USE_KIND" = false ] && [ -n "$CLUSTER_SUFFIX" ]; then
    hcp_managed_by="${MANAGED_BY_TAG:-kagenti-hypershift-custom}"
    hcp_cluster_name="${hcp_managed_by}-${CLUSTER_SUFFIX}"
    hcp_kubeconfig="$HOME/clusters/hcp/${hcp_cluster_name}/auth/kubeconfig"
    if [ -f "$hcp_kubeconfig" ]; then
        export KUBECONFIG="$hcp_kubeconfig"
        log_info "Using kubeconfig: $KUBECONFIG"
    fi
fi

# Discover UI URL
KAGENTI_UI_URL=$(discover_ui_url)
export KAGENTI_UI_URL
log_success "UI URL: $KAGENTI_UI_URL"

# Discover Keycloak credentials (now KUBECONFIG is set in this shell)
discover_keycloak_creds

# Ensure the Keycloak user exists in the demo realm (auto-provision on fresh clusters)
# Skip if credentials came from kagenti-test-user (already in demo realm by design)
ensure_demo_realm_user() {
    # If creds came from kagenti-test-user, the installer already created the user
    if [ "${KEYCLOAK_CRED_SOURCE:-}" = "kagenti-test-user" ]; then
        log_info "User from kagenti-test-user secret (already in demo realm)"
        return
    fi

    local cli="kubectl"
    command -v oc &>/dev/null && [ "$USE_KIND" = false ] && cli="oc"

    local kc_host
    kc_host=$($cli get route -n keycloak keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    [ -z "$kc_host" ] && return

    # Get master realm admin token (keycloak-initial-admin creds work on master realm)
    # Need to use keycloak-initial-admin for admin API access
    local kc_flag=""
    [ -n "${KUBECONFIG:-}" ] && kc_flag="--kubeconfig=$KUBECONFIG"
    local admin_user admin_pass
    admin_user=$($cli $kc_flag get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    admin_pass=$($cli $kc_flag get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    [ -z "$admin_user" ] && return

    local token
    token=$(curl -sk "https://$kc_host/realms/master/protocol/openid-connect/token" \
      -d "client_id=admin-cli" \
      -d "username=$admin_user" \
      -d "password=$admin_pass" \
      -d "grant_type=password" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
    [ -z "$token" ] && return

    # Check if user exists in demo realm
    local user_count
    user_count=$(curl -sk "https://$kc_host/admin/realms/demo/users?username=$KEYCLOAK_USER" \
      -H "Authorization: Bearer $token" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

    if [ "$user_count" = "0" ]; then
        log_info "Creating $KEYCLOAK_USER in Keycloak demo realm..."
        local http_code
        http_code=$(curl -sk -o /dev/null -w "%{http_code}" "https://$kc_host/admin/realms/demo/users" \
          -H "Authorization: Bearer $token" \
          -H "Content-Type: application/json" \
          -d "{
            \"username\": \"$KEYCLOAK_USER\",
            \"email\": \"admin@kagenti.local\",
            \"firstName\": \"Admin\",
            \"lastName\": \"User\",
            \"enabled\": true,
            \"emailVerified\": true,
            \"requiredActions\": [],
            \"credentials\": [{
              \"type\": \"password\",
              \"value\": \"$KEYCLOAK_PASS\",
              \"temporary\": false
            }]
          }" 2>/dev/null)
        if [ "$http_code" = "201" ]; then
            log_success "Created $KEYCLOAK_USER in demo realm"
        else
            log_warn "Failed to create user in demo realm (HTTP $http_code)"
        fi
    else
        log_info "User $KEYCLOAK_USER exists in demo realm"
    fi
}
ensure_demo_realm_user

# Discover additional service URLs for walkthrough tests
discover_service_url() {
    local ns="$1" name="$2"
    local cli="kubectl"
    command -v oc &>/dev/null && [ "$USE_KIND" = false ] && cli="oc"
    local host
    host=$($cli get route -n "$ns" "$name" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -n "$host" ]; then
        echo "https://$host"
    elif [ "$USE_KIND" = true ]; then
        echo "http://${name}.localtest.me:8080"
    fi
}

export MLFLOW_URL="${MLFLOW_URL:-$(discover_service_url kagenti-system mlflow)}"
export KIALI_URL="${KIALI_URL:-$(discover_service_url istio-system kiali)}"
export PHOENIX_URL="${PHOENIX_URL:-$(discover_service_url kagenti-system phoenix)}"

# Discover kubeadmin password for Kiali OAuth (HyperShift)
if [ -z "${KUBEADMIN_PASS:-}" ] && [ -n "${KUBECONFIG:-}" ]; then
    kubeadmin_file="$(dirname "$KUBECONFIG")/kubeadmin-password"
    if [ -f "$kubeadmin_file" ]; then
        export KUBEADMIN_PASS="$(cat "$kubeadmin_file")"
        log_info "Discovered kubeadmin password"
    fi
fi

[ -n "$MLFLOW_URL" ] && log_info "MLflow: $MLFLOW_URL"
[ -n "$KIALI_URL" ] && log_info "Kiali: $KIALI_URL"
[ -n "$PHOENIX_URL" ] && log_info "Phoenix: $PHOENIX_URL"

# Verify UI is reachable
log_info "Checking UI reachability..."
if curl -skL --connect-timeout 10 "$KAGENTI_UI_URL" >/dev/null 2>&1; then
    log_success "UI is reachable"
else
    log_warn "UI may not be reachable at $KAGENTI_UI_URL (continuing anyway)"
fi

# Set up paths for Playwright
# Per-test output dir enables parallel runs without stomping on each other
export PLAYWRIGHT_OUTPUT_DIR="$SCRIPT_DIR/test-results/${TEST_PREFIX:-all}"
mkdir -p "$PLAYWRIGHT_OUTPUT_DIR"

log_info "Repo path: $REPO_PATH"
log_info "Test dir: $E2E_DIR"
echo ""

# Ensure auth directory exists
mkdir -p "$SCRIPT_DIR/.auth"

# Ensure node_modules exists in ui-v2
cd "$UI_DIR"
if [ ! -d "$UI_DIR/node_modules/@playwright/test" ]; then
    log_info "Installing npm dependencies in $UI_DIR..."
    npm install
fi

# Check for npm vulnerabilities
log_info "Checking npm packages for vulnerabilities..."
AUDIT_OUTPUT=$(npm audit --json 2>/dev/null || true)
AUDIT_HIGH=$(echo "$AUDIT_OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    v = data.get('metadata', {}).get('vulnerabilities', {})
    high = v.get('high', 0)
    critical = v.get('critical', 0)
    moderate = v.get('moderate', 0)
    print(f'{critical}:{high}:{moderate}')
except:
    print('0:0:0')
" 2>/dev/null || echo "0:0:0")

AUDIT_CRITICAL=$(echo "$AUDIT_HIGH" | cut -d: -f1)
AUDIT_HIGH_COUNT=$(echo "$AUDIT_HIGH" | cut -d: -f2)
AUDIT_MODERATE=$(echo "$AUDIT_HIGH" | cut -d: -f3)

if [ "$AUDIT_CRITICAL" -gt 0 ] 2>/dev/null; then
    log_error "npm audit found $AUDIT_CRITICAL critical vulnerabilities"
    npm audit 2>/dev/null || true
    log_error "Fix with: cd $UI_DIR && npm audit fix"
    exit 1
elif [ "$AUDIT_HIGH_COUNT" -gt 0 ] 2>/dev/null; then
    log_error "npm audit found $AUDIT_HIGH_COUNT high severity vulnerabilities"
    npm audit 2>/dev/null || true
    log_error "Fix with: cd $UI_DIR && npm audit fix"
    exit 1
elif [ "$AUDIT_MODERATE" -gt 0 ] 2>/dev/null; then
    log_warn "npm audit found $AUDIT_MODERATE moderate vulnerabilities (continuing)"
else
    log_success "No high/critical npm vulnerabilities"
fi

# Set NODE_PATH so files outside ui-v2/ (like keycloak-auth-setup.ts) can resolve @playwright/test
export NODE_PATH="$UI_DIR/node_modules"

# Use the local playwright binary from ui-v2/node_modules
PLAYWRIGHT_BIN="$UI_DIR/node_modules/.bin/playwright"
if [ ! -x "$PLAYWRIGHT_BIN" ]; then
    log_error "Playwright binary not found at $PLAYWRIGHT_BIN"
    log_error "Run: cd $UI_DIR && npm install"
    exit 1
fi

# Ensure Playwright browsers are installed
log_info "Checking Playwright browsers..."
if ! "$PLAYWRIGHT_BIN" install --dry-run chromium >/dev/null 2>&1; then
    log_info "Installing Playwright Chromium browser..."
    "$PLAYWRIGHT_BIN" install chromium
fi

# Determine if we're running a local walkthrough test or a repo e2e test
IS_LOCAL_TEST=false
ACTIVE_TEST_DIR="./e2e"
if [ -n "$TEST_PREFIX" ] && [ -f "$LOCAL_E2E_DIR/${TEST_PREFIX}.spec.ts" ]; then
    IS_LOCAL_TEST=true
    ACTIVE_TEST_DIR="$LOCAL_E2E_DIR"
    log_info "Using local test: $LOCAL_E2E_DIR/${TEST_PREFIX}.spec.ts"
fi

# Generate a temporary Playwright config INSIDE ui-v2/ so module resolution works
TEMP_CONFIG="$UI_DIR/.playwright-video.config.cjs"
export AUTH_STATE_PATH="$SCRIPT_DIR/.auth/state.json"
GLOBAL_SETUP_PATH="$SCRIPT_DIR/keycloak-auth-setup.ts"

if [ "$IS_LOCAL_TEST" = true ]; then
    # Local walkthrough tests handle auth inline — no globalSetup or storageState
    cat > "$TEMP_CONFIG" << CONFIGEOF
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '${ACTIVE_TEST_DIR}',
  outputDir: '${PLAYWRIGHT_OUTPUT_DIR}',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.KAGENTI_UI_URL,
    video: { mode: 'on', size: { width: 1920, height: 1080 } },
    launchOptions: { slowMo: 300 },
    screenshot: 'on',
    trace: 'off',
    ignoreHTTPSErrors: true,
    viewport: { width: 1920, height: 1080 },
  },
  projects: [{ name: 'chromium', use: { viewport: { width: 1920, height: 1080 } } }],
});
CONFIGEOF
else
    # Repo e2e tests use globalSetup + storageState for Keycloak auth
    cat > "$TEMP_CONFIG" << CONFIGEOF
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '${ACTIVE_TEST_DIR}',
  outputDir: '${PLAYWRIGHT_OUTPUT_DIR}',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  globalSetup: '${GLOBAL_SETUP_PATH}',
  use: {
    baseURL: process.env.KAGENTI_UI_URL,
    video: { mode: 'on', size: { width: 1920, height: 1080 } },
    launchOptions: { slowMo: 500 },
    screenshot: 'on',
    trace: 'off',
    ignoreHTTPSErrors: true,
    storageState: '${AUTH_STATE_PATH}',
    viewport: { width: 1920, height: 1080 },
  },
  projects: [{ name: 'chromium', use: { viewport: { width: 1920, height: 1080 } } }],
});
CONFIGEOF
fi

# Force CommonJS for test files: create a package.json in e2e/ dirs that overrides
# the parent "type": "module". This avoids the ESM preflight check on Node 19.
E2E_PKG_JSON="$E2E_DIR/package.json"
E2E_PKG_EXISTED=false
if [ -f "$E2E_PKG_JSON" ]; then
    E2E_PKG_EXISTED=true
fi
if [ "$E2E_PKG_EXISTED" = false ]; then
    echo '{ "type": "commonjs" }' > "$E2E_PKG_JSON"
fi

# Also add CJS override for demos dir if running local tests
LOCAL_E2E_PKG="$LOCAL_E2E_DIR/package.json"
if [ ! -f "$LOCAL_E2E_PKG" ]; then
    echo '{ "type": "commonjs" }' > "$LOCAL_E2E_PKG"
fi

# Clean up temp files on exit
cleanup_temp() {
    rm -f "$TEMP_CONFIG"
    if [ "$E2E_PKG_EXISTED" = false ]; then
        rm -f "$E2E_PKG_JSON"
    fi
}
trap cleanup_temp EXIT

CONFIG_PATH="$TEMP_CONFIG"
log_info "Config: $CONFIG_PATH"

# ============================================================================
# Narration pipeline (automatic when OPENAI_API_KEY is set + narration file exists)
#
# 3-step pipeline:
#   Step 1: Fast run → measure video slot timing + generate TTS → validate
#   Step 2: If narration < slot for any section → STOP, tell LLM to expand narration
#   Step 3: Regenerate video with slots = narration_duration + 1s → composite voiceover
#
# Without OPENAI_API_KEY: just record video (step 1 only, no narration)
# ============================================================================
NARRATION_TEST_NAME="${TEST_PREFIX:-walkthrough-demo}"
NARRATION_FILE="$SCRIPT_DIR/narrations/${NARRATION_TEST_NAME}.txt"
SOURCE_TEST="$LOCAL_E2E_DIR/${NARRATION_TEST_NAME}.spec.ts"
NARRATION_DIR="$SCRIPT_DIR/e2e-narration"
HAS_NARRATION=false

if [ "$NO_NARRATION" = false ] && [ -n "${OPENAI_API_KEY:-}" ] && [ -f "$NARRATION_FILE" ] && [ -f "$SOURCE_TEST" ]; then
    HAS_NARRATION=true

    mkdir -p "$NARRATION_DIR"
    [ ! -f "$NARRATION_DIR/package.json" ] && echo '{ "type": "commonjs" }' > "$NARRATION_DIR/package.json"

    # ── Step 1: Fast run to measure video slot timing ────────────────
    log_info "Step 1/3: Fast run to measure video slot timing..."
    echo ""
    set +e
    "$PLAYWRIGHT_BIN" test --config="$CONFIG_PATH" "$NARRATION_TEST_NAME"
    PASS1_EXIT=$?
    set -e
    [ $PASS1_EXIT -ne 0 ] && log_warn "Step 1 exited with code $PASS1_EXIT (continuing)"
    echo ""

    # ── Generate TTS and measure narration durations ─────────────────
    log_info "Measuring narration durations (TTS generation)..."
    SYNCED_TEST="$NARRATION_DIR/${NARRATION_TEST_NAME}.spec.ts"
    PYTHONWARNINGS=ignore::DeprecationWarning uv run --with openai python3 "$SCRIPT_DIR/sync-narration.py" \
        --narration "$NARRATION_FILE" \
        --test "$SOURCE_TEST" \
        --output "$SYNCED_TEST" \
        --timestamps "$SCRIPT_DIR/${NARRATION_TEST_NAME}-timestamps.json" \
        --pauses-json "$SCRIPT_DIR/${NARRATION_TEST_NAME}-section-pauses.json" || {
        log_warn "Narration sync failed"
        HAS_NARRATION=false
    }

    if [ "$HAS_NARRATION" = true ] && [ -f "$SYNCED_TEST" ]; then
        # ── Step 3: Regenerate video with narration-synced timing ────
        IS_LOCAL_TEST=true
        ACTIVE_TEST_DIR="$NARRATION_DIR"
        TEST_PREFIX="${NARRATION_TEST_NAME}"

        cat > "$TEMP_CONFIG" << CONFIGEOF
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '${ACTIVE_TEST_DIR}',
  outputDir: '${PLAYWRIGHT_OUTPUT_DIR}',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.KAGENTI_UI_URL,
    video: { mode: 'on', size: { width: 1920, height: 1080 } },
    launchOptions: { slowMo: 300 },
    screenshot: 'on',
    trace: 'off',
    ignoreHTTPSErrors: true,
    viewport: { width: 1920, height: 1080 },
  },
  projects: [{ name: 'chromium', use: { viewport: { width: 1920, height: 1080 } } }],
});
CONFIGEOF

        rm -rf "$PLAYWRIGHT_OUTPUT_DIR"
        echo ""
        log_info "Step 3/3: Recording narration-synced video..."
        echo ""
    fi
fi

if [ "$RUN_ALL" = true ]; then
    log_info "Running ALL Playwright tests with video recording..."
elif [ -n "$TEST_PREFIX" ]; then
    log_info "Running tests matching prefix: $TEST_PREFIX"
fi

echo ""

# Run Playwright from ui-v2 directory
set +e
if [ "$RUN_ALL" = true ]; then
    echo -e "${BLUE}Running:${NC} playwright test --config=.playwright-video.config.cjs"
    echo ""
    "$PLAYWRIGHT_BIN" test --config="$CONFIG_PATH"
elif [ -n "$TEST_PREFIX" ]; then
    echo -e "${BLUE}Running:${NC} playwright test --config=.playwright-video.config.cjs $TEST_PREFIX"
    echo ""
    "$PLAYWRIGHT_BIN" test --config="$CONFIG_PATH" "$TEST_PREFIX"
fi
PLAYWRIGHT_EXIT=$?
set -e

if [ $PLAYWRIGHT_EXIT -ne 0 ]; then
    log_warn "Playwright exited with code $PLAYWRIGHT_EXIT (some tests may have failed)"
fi

# ============================================================================
# Collect and rename video files — organized per scenario in demos/<category>/
# Uses demo-map.json for nested directory structure.
# Creates timestamped files + _latest copies (overwritten each run).
# Collocates test spec, narration, and timestamps alongside videos.
# ============================================================================
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M')
SCENARIO_NAME="${TEST_PREFIX:-all}"
DEMO_DIR=$(get_demo_dir "$SCENARIO_NAME")
mkdir -p "$DEMO_DIR"

VIDEO_COUNT=0

# Relative path for display
DEMO_DIR_REL="${DEMO_DIR#$SCRIPT_DIR/}"
log_info "Collecting recorded videos to ${DEMO_DIR_REL}/..."

# Playwright stores videos in test-results/<test>/<test-hash>/video.webm
if [ -d "$PLAYWRIGHT_OUTPUT_DIR" ]; then
    while IFS= read -r -d '' video_file; do
        parent_dir=$(basename "$(dirname "$video_file")")
        test_name=$(echo "$parent_dir" | sed 's/-chromium$//' | sed 's/-[0-9]*$//')

        # Timestamped copy
        dest_name="${SCENARIO_NAME}_${TIMESTAMP}.webm"
        dest_path="$DEMO_DIR/$dest_name"
        cp "$video_file" "$dest_path"

        # _latest copy (always overwritten)
        latest_path="$DEMO_DIR/${SCENARIO_NAME}_latest.webm"
        cp "$video_file" "$latest_path"

        log_success "Video: ${DEMO_DIR_REL}/$dest_name"
        log_success "Latest: ${DEMO_DIR_REL}/${SCENARIO_NAME}_latest.webm"
        VIDEO_COUNT=$((VIDEO_COUNT + 1))

        # Attempt voiceover if OPENAI_API_KEY is set
        if [ -n "${OPENAI_API_KEY:-}" ]; then
            PYTHONWARNINGS=ignore::DeprecationWarning uv run --with openai \
                "$SCRIPT_DIR/add-voiceover.py" "$dest_path" || {
                log_warn "Voiceover generation failed for $dest_name (continuing without)"
            }
            # Create _latest copies for narration and voiceover too
            voiceover_ts="${dest_path%.webm}_voiceover.mp4"
            narration_ts="${dest_path%.webm}_narration.mp3"
            [ -f "$voiceover_ts" ] && cp "$voiceover_ts" "$DEMO_DIR/${SCENARIO_NAME}_latest_voiceover.mp4"
            [ -f "$narration_ts" ] && cp "$narration_ts" "$DEMO_DIR/${SCENARIO_NAME}_latest_narration.mp3"
        fi
    done < <(find "$PLAYWRIGHT_OUTPUT_DIR" -name "video.webm" -print0 2>/dev/null)
fi

# ============================================================================
# Collocate artifacts alongside videos
# ============================================================================
# Copy test spec
SOURCE_SPEC="$LOCAL_E2E_DIR/${SCENARIO_NAME}.spec.ts"
[ -f "$SOURCE_SPEC" ] && cp "$SOURCE_SPEC" "$DEMO_DIR/${SCENARIO_NAME}.spec.ts"

# Copy narration file
NARR_SRC="$SCRIPT_DIR/narrations/${SCENARIO_NAME}.txt"
[ -f "$NARR_SRC" ] && cp "$NARR_SRC" "$DEMO_DIR/${SCENARIO_NAME}.txt"

# Copy timestamps
TS_FILE="$SCRIPT_DIR/${SCENARIO_NAME}-timestamps.json"
[ ! -f "$TS_FILE" ] && TS_FILE="$SCRIPT_DIR/walkthrough-timestamps.json"
[ -f "$TS_FILE" ] && cp "$TS_FILE" "$DEMO_DIR/${SCENARIO_NAME}-timestamps.json"

# Copy section pauses if they exist
PAUSES_FILE="$SCRIPT_DIR/${SCENARIO_NAME}-section-pauses.json"
[ ! -f "$PAUSES_FILE" ] && PAUSES_FILE="$SCRIPT_DIR/section-pauses.json"
[ -f "$PAUSES_FILE" ] && cp "$PAUSES_FILE" "$DEMO_DIR/${SCENARIO_NAME}-section-pauses.json"

echo ""
if [ $VIDEO_COUNT -gt 0 ]; then
    log_success "Recorded $VIDEO_COUNT video(s) in ${DEMO_DIR_REL}/"
else
    log_warn "No videos were recorded. Check test output above for errors."
fi

# Voiceover status
if [ -n "${OPENAI_API_KEY:-}" ]; then
    voiceover_count=$(find "$DEMO_DIR" -name "*_voiceover.mp4" -newer "$PLAYWRIGHT_OUTPUT_DIR" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$voiceover_count" -gt 0 ]; then
        log_success "Generated $voiceover_count voiceover video(s)"
    fi
else
    log_info "Set OPENAI_API_KEY to add voiceover to recordings"
fi

# ============================================================================
# Run validation (always after --sync, optional otherwise)
# ============================================================================
if [ -f "$DEMO_DIR/${SCENARIO_NAME}-timestamps.json" ] && [ -f "$DEMO_DIR/${SCENARIO_NAME}.txt" ]; then
    echo ""
    log_info "Running alignment validation..."
    python3 "$SCRIPT_DIR/validate-alignment.py" \
        --timestamps "$DEMO_DIR/${SCENARIO_NAME}-timestamps.json" \
        --narration "$DEMO_DIR/${SCENARIO_NAME}.txt" 2>/dev/null || {
        log_warn "Alignment validation failed — check output above"
    }
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}┃${NC} Done! Demo files in: $DEMO_DIR/"
echo -e "${GREEN}┃${NC}"
echo -e "${GREEN}┃${NC} Contents:"
ls -1 "$DEMO_DIR/" 2>/dev/null | while read -r f; do
    echo -e "${GREEN}┃${NC}   $f"
done
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

exit $PLAYWRIGHT_EXIT
