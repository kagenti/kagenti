#!/usr/bin/env bash
# ============================================================================
# KIND INSTALLER MATRIX TEST HARNESS
# ============================================================================
# Runs setup-kagenti.sh with multiple flag combinations (profiles), then
# executes the pytest installer tests after each to verify correctness.
#
# Default: cleanup+reuse cluster between profiles (fastest).
# Use --fresh-cluster for full isolation (destroy+recreate per profile).
#
# Usage:
#   scripts/kind/test-installer-matrix.sh                     # All 5 profiles
#   scripts/kind/test-installer-matrix.sh --profile core,full # Subset
#   scripts/kind/test-installer-matrix.sh --fresh-cluster     # Full isolation
#   scripts/kind/test-installer-matrix.sh --keep-cluster      # Keep for debug
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Defaults ─────────────────────────────────────────────────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-kagenti-matrix}"
KIND_CONFIG="${KIND_CONFIG:-$REPO_ROOT/scripts/kind/kind-config-registry.yaml}"
LOG_DIR="${LOG_DIR:-/tmp/kagenti/matrix}"
FRESH_CLUSTER=false
KEEP_CLUSTER=false
SELECTED_PROFILES=""

# ── Colors & logging ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

# ── Profile definitions ────────────────────────────────────────────────────
# Format: PROFILE_NAME="--with-flag1 --with-flag2 ..."
# Empty string = core only (no flags)
declare -A PROFILES
PROFILES=(
  [core]=""
  [platform]="--with-ui --with-builds"
  [observability]="--with-otel --with-mlflow"
  [mesh]="--with-istio --with-spire --with-kiali"
  [full]="--with-all"
)

# Ordered list (bash associative arrays don't preserve order)
ALL_PROFILES=(core platform observability mesh full)

# ── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)       SELECTED_PROFILES="$2"; shift 2 ;;
    --fresh-cluster) FRESH_CLUSTER=true; shift ;;
    --keep-cluster)  KEEP_CLUSTER=true; shift ;;
    --cluster-name)  CLUSTER_NAME="$2"; shift 2 ;;
    --log-dir)       LOG_DIR="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --profile NAMES    Comma-separated profiles to run (default: all)"
      echo "                     Available: core, platform, observability, mesh, full"
      echo "  --fresh-cluster    Destroy+recreate Kind cluster per profile (slow but clean)"
      echo "  --keep-cluster     Don't destroy cluster at end (for debugging)"
      echo "  --cluster-name N   Kind cluster name (default: kagenti-matrix)"
      echo "  --log-dir DIR      Log directory (default: /tmp/kagenti/matrix)"
      echo ""
      echo "Profiles:"
      echo "  core           No flags — core components only"
      echo "  platform       --with-ui --with-builds"
      echo "  observability  --with-otel --with-mlflow"
      echo "  mesh           --with-istio --with-spire --with-kiali"
      echo "  full           --with-all"
      echo ""
      echo "Examples:"
      echo "  $0                             # Run all 5 profiles"
      echo "  $0 --profile core,full         # Quick sanity check"
      echo "  $0 --fresh-cluster             # Full isolation mode"
      echo "  $0 --profile core --keep-cluster  # Debug a single profile"
      exit 0 ;;
    *) log_error "Unknown option: $1"; exit 1 ;;
  esac
done

# Build profile list
if [[ -n "$SELECTED_PROFILES" ]]; then
  IFS=',' read -ra RUN_PROFILES <<< "$SELECTED_PROFILES"
  for p in "${RUN_PROFILES[@]}"; do
    if [[ -z "${PROFILES[$p]+x}" ]]; then
      log_error "Unknown profile: $p"
      log_error "Available: ${ALL_PROFILES[*]}"
      exit 1
    fi
  done
else
  RUN_PROFILES=("${ALL_PROFILES[@]}")
fi

# ── Pre-flight checks ──────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Kind Installer Matrix Test"
echo "============================================"
echo ""
echo "  Cluster:       $CLUSTER_NAME"
echo "  Profiles:      ${RUN_PROFILES[*]}"
echo "  Fresh cluster: $FRESH_CLUSTER"
echo "  Log dir:       $LOG_DIR"
echo ""

for cmd in kind helm kubectl uv; do
  if ! command -v "$cmd" &>/dev/null; then
    log_error "$cmd not found in PATH"
    exit 1
  fi
done
log_success "All prerequisites found"

mkdir -p "$LOG_DIR"

# ── Setup script argument parsing validation ───────────────────────────────
log_info "Validating setup-kagenti.sh argument parsing..."
SETUP_SCRIPT="$REPO_ROOT/scripts/kind/setup-kagenti.sh"
VALIDATION_FAILED=false

# Test 1: Default case (no flags) - would have caught the unbound variable bug
if ! OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null 2>&1 | head -30 || true); then
  log_error "Setup script crashed with default settings"
  VALIDATION_FAILED=true
elif ! echo "$OUTPUT" | grep -q "Kagenti helm --values overrides:"; then
  log_error "Setup script didn't reach config display"
  VALIDATION_FAILED=true
fi

# Test 2: Verify 'none' is displayed for empty values overrides
if ! echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: none"; then
  log_error "Setup script doesn't show 'none' for empty kagenti values"
  VALIDATION_FAILED=true
fi
if ! echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: none"; then
  log_error "Setup script doesn't show 'none' for empty kagenti-deps values"
  VALIDATION_FAILED=true
fi

# Test 3: Verify script handles --kagenti-values override
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster --kagenti-values test.yaml </dev/null 2>&1 | head -30 || true)
if ! echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values test.yaml"; then
  log_error "Setup script doesn't handle --kagenti-values correctly"
  VALIDATION_FAILED=true
fi

# Test 4: Verify strict mode is enabled
if ! head -30 "$SETUP_SCRIPT" | grep -q "set -euo pipefail"; then
  log_warn "Setup script missing strict mode (set -euo pipefail)"
fi

if $VALIDATION_FAILED; then
  log_error "Setup script validation failed"
  exit 1
fi
log_success "Setup script argument parsing validated"
echo ""

# ── Result tracking ────────────────────────────────────────────────────────
declare -a RESULT_PROFILE RESULT_INSTALL RESULT_TESTS
declare -a RESULT_PASSED RESULT_SKIPPED RESULT_FAILED RESULT_DURATION

OVERALL_START=$SECONDS
ANY_FAILURE=false

# ── Helpers ────────────────────────────────────────────────────────────────

_create_cluster() {
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log_success "Cluster '$CLUSTER_NAME' already exists — reusing"
  else
    log_info "Creating Kind cluster '$CLUSTER_NAME'..."
    if ! kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG" \
        > "$LOG_DIR/cluster-create.log" 2>&1; then
      log_error "Cluster creation failed (see $LOG_DIR/cluster-create.log)"
      return 1
    fi
    log_success "Cluster created"
  fi
  kubectl cluster-info --context "kind-${CLUSTER_NAME}" &>/dev/null || true
}

_destroy_cluster() {
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log_info "Destroying cluster '$CLUSTER_NAME'..."
    kind delete cluster --name "$CLUSTER_NAME" > "$LOG_DIR/cluster-destroy.log" 2>&1 || true
    log_success "Cluster destroyed"
  fi
}

_cleanup_platform() {
  log_info "Cleaning up platform (helm uninstall)..."
  "$SCRIPT_DIR/cleanup-kagenti.sh" --cluster-name "$CLUSTER_NAME" \
    > "$LOG_DIR/cleanup.log" 2>&1 || true
  log_success "Cleanup done"
}

_parse_pytest_summary() {
  local log_file="$1"
  local line
  line=$(grep -E '[0-9]+ (passed|skipped|failed|error)' "$log_file" | tail -1 || echo "")
  local passed=0 skipped=0 failed=0

  if [[ -n "$line" ]]; then
    passed=$(echo "$line" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
    skipped=$(echo "$line" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo 0)
    failed=$(echo "$line" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)
    local errors
    errors=$(echo "$line" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo 0)
    failed=$(( ${failed:-0} + ${errors:-0} ))
  fi

  echo "${passed:-0} ${skipped:-0} ${failed:-0}"
}

_format_duration() {
  local secs=$1
  printf "%dm %02ds" $((secs / 60)) $((secs % 60))
}

# ── Initial cluster creation ───────────────────────────────────────────────
if ! $FRESH_CLUSTER; then
  if ! _create_cluster; then
    log_error "Cannot create initial cluster — aborting"
    exit 1
  fi
fi

# ── Run each profile ───────────────────────────────────────────────────────
PROFILE_INDEX=0
PROFILE_COUNT=${#RUN_PROFILES[@]}

for profile in "${RUN_PROFILES[@]}"; do
  PROFILE_INDEX=$((PROFILE_INDEX + 1))
  flags="${PROFILES[$profile]}"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Profile ${PROFILE_INDEX}/${PROFILE_COUNT}: $profile"
  if [[ -n "$flags" ]]; then
    echo "  Flags: $flags"
  else
    echo "  Flags: (none — core only)"
  fi
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  PROFILE_START=$SECONDS
  install_status="OK"
  test_status="OK"
  passed=0; skipped=0; failed=0
  cluster_ok=true

  # ── Cluster prep ──────────────────────────────────────────────────────
  if $FRESH_CLUSTER; then
    _destroy_cluster
    if ! _create_cluster; then
      log_error "Cluster creation failed for profile '$profile'"
      cluster_ok=false
      install_status="FAIL"
      ANY_FAILURE=true
    fi
  elif [[ $PROFILE_INDEX -gt 1 ]]; then
    _cleanup_platform
  fi

  # ── Install ───────────────────────────────────────────────────────────
  install_log="$LOG_DIR/${profile}-install.log"

  if $cluster_ok; then
    log_info "Installing (flags: ${flags:-none})..."

    # shellcheck disable=SC2086
    if "$SCRIPT_DIR/setup-kagenti.sh" --skip-cluster --build-images --cluster-name "$CLUSTER_NAME" \
        $flags > "$install_log" 2>&1; then
      log_success "Install succeeded"
    else
      log_error "Install FAILED (see $install_log)"
      install_status="FAIL"
      ANY_FAILURE=true
    fi
  else
    echo "Skipped — cluster creation failed" > "$install_log"
  fi

  # ── Run tests ─────────────────────────────────────────────────────────
  test_log="$LOG_DIR/${profile}-tests.log"

  if [[ "$install_status" == "OK" ]]; then
    log_info "Running tests..."

    flags_for_env="$flags"
    if [[ -z "$flags_for_env" ]]; then
      flags_for_env="--core-only"
    fi

    if KIND_INSTALLER_FLAGS="$flags_for_env" \
       uv run pytest "$REPO_ROOT/kagenti/tests/e2e/common/test_kind_installer.py" \
       -v --tb=short > "$test_log" 2>&1; then
      log_success "Tests passed"
    else
      log_error "Tests FAILED (see $test_log)"
      test_status="FAIL"
      ANY_FAILURE=true
    fi

    read -r passed skipped failed <<< "$(_parse_pytest_summary "$test_log")"
  else
    log_warn "Skipping tests (install failed)"
    test_status="SKIP"
    echo "Tests skipped — install failed" > "$test_log"
  fi

  # ── Record results ────────────────────────────────────────────────────
  duration=$(( SECONDS - PROFILE_START ))

  RESULT_PROFILE+=("$profile")
  RESULT_INSTALL+=("$install_status")
  RESULT_TESTS+=("$test_status")
  RESULT_PASSED+=("$passed")
  RESULT_SKIPPED+=("$skipped")
  RESULT_FAILED+=("$failed")
  RESULT_DURATION+=("$(_format_duration "$duration")")

  log_info "Profile '$profile' done in $(_format_duration "$duration")"
done

# ── Cleanup ────────────────────────────────────────────────────────────────
echo ""
if ! $KEEP_CLUSTER; then
  _destroy_cluster
else
  log_info "Keeping cluster '$CLUSTER_NAME' (--keep-cluster)"
fi

# ── Summary table ──────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Matrix Test Results"
echo "============================================"
echo ""

# Header
printf "  ${BOLD}%-16s %-9s %-7s %6s %6s %6s %10s${NC}\n" \
  "Profile" "Install" "Tests" "Pass" "Skip" "Fail" "Duration"
printf "  %-16s %-9s %-7s %6s %6s %6s %10s\n" \
  "────────────────" "─────────" "───────" "──────" "──────" "──────" "──────────"

for i in "${!RESULT_PROFILE[@]}"; do
  install_color="$GREEN"
  [[ "${RESULT_INSTALL[$i]}" != "OK" ]] && install_color="$RED"

  test_color="$GREEN"
  [[ "${RESULT_TESTS[$i]}" == "FAIL" ]] && test_color="$RED"
  [[ "${RESULT_TESTS[$i]}" == "SKIP" ]] && test_color="$YELLOW"

  fail_color="$NC"
  [[ "${RESULT_FAILED[$i]}" -gt 0 ]] 2>/dev/null && fail_color="$RED"

  printf "  %-16s ${install_color}%-9s${NC} ${test_color}%-7s${NC} %6s %6s ${fail_color}%6s${NC} %10s\n" \
    "${RESULT_PROFILE[$i]}" \
    "${RESULT_INSTALL[$i]}" \
    "${RESULT_TESTS[$i]}" \
    "${RESULT_PASSED[$i]}" \
    "${RESULT_SKIPPED[$i]}" \
    "${RESULT_FAILED[$i]}" \
    "${RESULT_DURATION[$i]}"
done

echo ""
TOTAL_DURATION=$(( SECONDS - OVERALL_START ))
echo "  Total time: $(_format_duration "$TOTAL_DURATION")"
echo "  Logs: $LOG_DIR/"
echo ""

if $ANY_FAILURE; then
  log_error "One or more profiles failed"
  exit 1
else
  log_success "All profiles passed"
  exit 0
fi
