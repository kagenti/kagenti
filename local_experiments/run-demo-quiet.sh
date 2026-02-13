#!/usr/bin/env bash
# Quiet wrapper for run-playwright-demo.sh — captures verbose output to log file,
# prints only the summary. Safe for use as Claude Code background tasks.
#
# Usage: ./run-demo-quiet.sh --cluster-suffix <SUFFIX> --test <name>
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_NAME=""
ARGS=("$@")

# Extract test name from args
for i in "${!ARGS[@]}"; do
    if [ "${ARGS[$i]}" = "--test" ] && [ $((i+1)) -lt ${#ARGS[@]} ]; then
        TEST_NAME="${ARGS[$((i+1))]}"
        break
    fi
done

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${TEST_NAME:-all}_$(date '+%Y%m%d_%H%M%S').log"

echo "=== $TEST_NAME ==="
echo "Log: $LOG_FILE"

# Run the full pipeline, capture everything to log file
"$SCRIPT_DIR/run-playwright-demo.sh" "${ARGS[@]}" > "$LOG_FILE" 2>&1
EXIT_CODE=$?

# Extract just the key results from the log
grep -E "(✓|✗|passed|failed|Error:|fits|OVERFLOW|Coverage|Video:|Latest:|voiceover)" "$LOG_FILE" | head -20

if [ $EXIT_CODE -eq 0 ]; then
    echo "RESULT: PASS"
else
    echo "RESULT: FAIL (see $LOG_FILE)"
fi
echo ""
exit $EXIT_CODE
