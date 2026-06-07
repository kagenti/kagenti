#!/usr/bin/env bash
# Test script for setup-kagenti.sh to catch regression bugs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_SCRIPT="$SCRIPT_DIR/setup-kagenti.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TESTS_PASSED=0
TESTS_FAILED=0

log_test() {
  echo -e "\n${YELLOW}TEST:${NC} $1"
}

log_pass() {
  echo -e "${GREEN}✓ PASS${NC}: $1"
  ((TESTS_PASSED++))
}

log_fail() {
  echo -e "${RED}✗ FAIL${NC}: $1"
  ((TESTS_FAILED++))
}

# Test 1: Script should not crash with no arguments (dry-run)
log_test "Script accepts no arguments without crashing"
if OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 2>&1 | head -30) && echo "$OUTPUT" | grep -q "Kagenti helm --values overrides:"; then
  log_pass "No crash with default settings"
else
  log_fail "Script crashed or didn't reach config display"
fi

# Test 2: Script should show "none" when no values overrides provided
log_test "Shows 'none' for empty values overrides"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 2>&1 | head -30)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: none"; then
  log_pass "Shows 'none' for empty kagenti values"
else
  log_fail "Did not show 'none' for empty kagenti values"
fi

if echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: none"; then
  log_pass "Shows 'none' for empty kagenti-deps values"
else
  log_fail "Did not show 'none' for empty kagenti-deps values"
fi

# Test 3: Script should handle single values override
log_test "Handles single --kagenti-values override"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 --kagenti-values test.yaml 2>&1)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values test.yaml"; then
  log_pass "Shows single override correctly"
else
  log_fail "Did not show single override correctly"
fi

# Test 4: Script should handle multiple values overrides
log_test "Handles multiple --kagenti-values overrides"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 --kagenti-values test1.yaml --kagenti-values test2.yaml 2>&1)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values test1.yaml --values test2.yaml"; then
  log_pass "Shows multiple overrides correctly"
else
  log_fail "Did not show multiple overrides correctly"
fi

# Test 5: Script should handle --kagenti-deps-values
log_test "Handles --kagenti-deps-values override"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 --kagenti-deps-values deps.yaml 2>&1)
if echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: --values deps.yaml"; then
  log_pass "Shows deps override correctly"
else
  log_fail "Did not show deps override correctly"
fi

# Test 6: Script should handle both overrides together
log_test "Handles both kagenti and kagenti-deps overrides"
OUTPUT=$("$SETUP_SCRIPT" --dry-run --skip-cluster 2>&1 | head -30 --kagenti-values app.yaml --kagenti-deps-values deps.yaml 2>&1)
if echo "$OUTPUT" | grep -q "Kagenti helm --values overrides: --values app.yaml" && \
   echo "$OUTPUT" | grep -q "Kagenti-deps helm --values overrides: --values deps.yaml"; then
  log_pass "Shows both overrides correctly"
else
  log_fail "Did not show both overrides correctly"
fi

# Test 7: Verify script has strict mode enabled
log_test "Script uses strict mode (set -euo pipefail)"
if head -30 "$SETUP_SCRIPT" | grep -q "set -euo pipefail"; then
  log_pass "Script has strict mode enabled"
else
  log_fail "Script missing strict mode"
fi

# Summary
echo ""
echo "================================================"
echo "Test Results"
echo "================================================"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"
echo "================================================"

if [ $TESTS_FAILED -gt 0 ]; then
  exit 1
else
  exit 0
fi
