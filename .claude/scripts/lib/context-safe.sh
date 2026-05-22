#!/usr/bin/env bash
# context-safe.sh - Helper functions for keeping Claude Code context window small
#
# These functions redirect command output to log files and return only
# exit codes + brief summaries to the conversation context.
#
# Log directory convention:
#   TDD sessions:  /tmp/kagenti/tdd/$WORKTREE/   (worktree-scoped, survives iterations)
#   RCA sessions:  /tmp/kagenti/rca/$WORKTREE/   (worktree-scoped)
#   K8s debugging: /tmp/kagenti/k8s/$CLUSTER/    (cluster-scoped)
#   General:       /tmp/kagenti/logs/$$-<timestamp>/ (PID-scoped, unique per session)
#
# Usage in skills:
#   export CONTEXT_SAFE_LOG_DIR=/tmp/kagenti/tdd/$WORKTREE
#   source .claude/scripts/lib/context-safe.sh
#   run_captured "Deploy kagenti" $CONTEXT_SAFE_LOG_DIR/deploy.log helm upgrade ...
#
# Or inline (without sourcing):
#   command > $LOG_DIR/output.log 2>&1 && echo "OK" || echo "FAIL (see $LOG_DIR/output.log)"

CONTEXT_SAFE_LOG_DIR="${CONTEXT_SAFE_LOG_DIR:-/tmp/kagenti/logs/$$-$(date +%s)}"
mkdir -p "$CONTEXT_SAFE_LOG_DIR" 2>/dev/null

# Run a command with output captured to a specific file.
# Usage: run_captured "description" output_file command [args...]
# Returns: exit code of the command
# Prints: "OK: description" or "FAIL: description (exit=N, see output_file)"
run_captured() {
    local desc="$1" output_file="$2"
    shift 2
    mkdir -p "$(dirname "$output_file")" 2>/dev/null
    "$@" > "$output_file" 2>&1
    local rc=$?
    if [ $rc -eq 0 ]; then
        echo "OK: $desc"
    else
        echo "FAIL: $desc (exit=$rc, see $output_file)"
    fi
    return $rc
}

# Run a command quietly, showing only a summary.
# On failure, shows last N lines (default 5) for quick diagnosis.
# Full output is always available in the log file.
# Usage: run_quiet "description" command [args...]
# Usage: TAIL_LINES=10 run_quiet "description" command [args...]
run_quiet() {
    local desc="$1"
    shift
    local tail_lines="${TAIL_LINES:-5}"
    local output_file="${CONTEXT_SAFE_LOG_DIR}/cmd-$$-$(date +%s).log"
    "$@" > "$output_file" 2>&1
    local rc=$?
    if [ $rc -eq 0 ]; then
        echo "OK: $desc"
    else
        echo "FAIL: $desc (exit=$rc, log=$output_file)"
        echo "--- last $tail_lines lines ---"
        tail -"$tail_lines" "$output_file"
        echo "---"
    fi
    return $rc
}

# Run kubectl command with output to file.
# Usage: kube_captured "description" output_file kubectl_args...
# Example: kube_captured "list pods" /tmp/pods.log get pods -n kagenti-system
kube_captured() {
    local desc="$1" output_file="$2"
    shift 2
    run_captured "$desc" "$output_file" kubectl "$@"
}

# Run a test suite and parse results.
# Usage: run_tests "description" output_file test_command [args...]
# Prints: "PASS: description (N tests)" or "FAIL: description (N failed, see output_file)"
run_tests() {
    local desc="$1" output_file="$2"
    shift 2
    "$@" > "$output_file" 2>&1
    local rc=$?
    if [ $rc -eq 0 ]; then
        # Try to extract test count from pytest output
        local count
        count=$(grep -oP '\d+ passed' "$output_file" 2>/dev/null | head -1)
        echo "PASS: $desc${count:+ ($count)}"
    else
        local failed
        failed=$(grep -oP '\d+ failed' "$output_file" 2>/dev/null | head -1)
        echo "FAIL: $desc${failed:+ ($failed)} (exit=$rc, see $output_file)"
        echo "--- last 5 lines ---"
        tail -5 "$output_file"
        echo "---"
    fi
    return $rc
}

# Clean up old log files (older than 1 hour)
cleanup_logs() {
    find "$CONTEXT_SAFE_LOG_DIR" -name "cmd-*" -mmin +60 -delete 2>/dev/null
    echo "OK: Cleaned up old logs"
}
