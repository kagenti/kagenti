#!/usr/bin/env bash
# Unit tests for scripts/kind/setup-kagenti.sh
# These tests validate argument parsing and configuration display without
# actually creating clusters or installing components.
#
# Usage:
#   ./.github/scripts/kind/test-setup-script.sh
#
# Exit codes:
#   0 - All tests passed
#   1 - One or more tests failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SETUP_SCRIPT="$REPO_ROOT/scripts/kind/setup-kagenti.sh"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0

log_header() {
  echo -e "\n${BLUE}================================================${NC}"
  echo -e "${BLUE}$1${NC}"
  echo -e "${BLUE}================================================${NC}\n"
}

log_test() {
  echo -e "${YELLOW}TEST:${NC} $1"
}

log_pass() {
  echo -e "  ${GREEN}✓ PASS${NC}: $1"
  ((TESTS_PASSED++))
}

log_fail() {
  echo -e "  ${RED}✗ FAIL${NC}: $1"
  ((TESTS_FAILED++))
}

log_header "Testing setup-kagenti.sh Configuration Display"

# Test 1: Script accepts no arguments without crashing
log_test "Script runs with defaults (no flags)"
# Note: 'head' can cause SIGPIPE, so we capture output differently
if OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null 2>&1 </dev/null | head -30 || true); then
  if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides:"; then
    log_pass "No crash with default settings"
  else
    log_fail "Script didn't reach config display"
    echo "$OUTPUT" | tail -10
  fi
else
  log_fail "Script crashed with default settings"
fi

# Test 2: Displays 'none' for empty values overrides
log_test "Shows 'none' when no --kagenti-values provided"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: none"; then
  log_pass "Kagenti values shows 'none'"
else
  log_fail "Kagenti values doesn't show 'none'"
fi

if echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: none"; then
  log_pass "Kagenti-deps values shows 'none'"
else
  log_fail "Kagenti-deps values doesn't show 'none'"
fi

# Test 3: Handles single --kagenti-values override
log_test "Handles single --kagenti-values override"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null --kagenti-values test.yaml 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values test.yaml"; then
  log_pass "Single override displayed correctly"
else
  log_fail "Single override not displayed correctly"
fi

# Test 4: Handles multiple --kagenti-values overrides
log_test "Handles multiple --kagenti-values overrides"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null --kagenti-values test1.yaml --kagenti-values test2.yaml 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values test1.yaml --values test2.yaml"; then
  log_pass "Multiple overrides displayed correctly"
else
  log_fail "Multiple overrides not displayed correctly"
fi

# Test 5: Handles --kagenti-deps-values override
log_test "Handles --kagenti-deps-values override"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null --kagenti-deps-values deps.yaml 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: --values deps.yaml"; then
  log_pass "Deps override displayed correctly"
else
  log_fail "Deps override not displayed correctly"
fi

# Test 6: Handles both overrides together
log_test "Handles both kagenti and kagenti-deps overrides"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster </dev/null --kagenti-values app.yaml --kagenti-deps-values deps.yaml 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values app.yaml" && \
   echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: --values deps.yaml"; then
  log_pass "Both overrides displayed correctly"
else
  log_fail "Both overrides not displayed correctly"
fi

# Test 7: Verify strict mode is enabled
log_test "Script uses strict mode (set -euo pipefail)"
if head -30 "$SETUP_SCRIPT" | grep -q "set -euo pipefail"; then
  log_pass "Strict mode enabled"
else
  log_fail "Strict mode not enabled - script should use 'set -euo pipefail'"
fi

# Test 8: Verify help text is accessible
log_test "Help text is accessible"
if "$SETUP_SCRIPT" --help 2>&1 | grep -q "Usage:"; then
  log_pass "Help text displays"
else
  log_fail "Help text not accessible"
fi

# Summary
log_header "Test Results"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
  echo -e "${RED}Failed: $TESTS_FAILED${NC}"
fi
echo ""

if [ $TESTS_FAILED -gt 0 ]; then
  echo -e "${RED}❌ Tests FAILED${NC}"
  exit 1
else
  echo -e "${GREEN}✅ All tests PASSED${NC}"
  exit 0
fi
