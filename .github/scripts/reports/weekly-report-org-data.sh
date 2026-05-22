#!/usr/bin/env bash
# Gather weekly report data across all kagenti org repos
# Usage: ./weekly-report-org-data.sh [days] [org]
# Output: Per-repo JSON in /tmp/kagenti/github/data/<repo>/ + org-summary.json

set -euo pipefail

DAYS="${1:-7}"
ORG="${2:-kagenti}"
BASE_DIR="/tmp/kagenti/github/data"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$BASE_DIR"

SINCE=$(date -v-${DAYS}d -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -d "${DAYS} days ago" -u +"%Y-%m-%dT%H:%M:%SZ")

echo "=== Org-wide data gathering: $ORG (last $DAYS days, since $SINCE) ==="
echo ""

# Discover all non-archived repos
REPOS=$(gh repo list "$ORG" --no-archived --limit 100 --json name --jq '.[].name' | sort)
REPO_COUNT=$(echo "$REPOS" | wc -w | tr -d ' ')
echo "Found $REPO_COUNT non-archived repos in $ORG"
echo ""

# Gather data per repo
ACTIVE_REPOS=()
QUIET_REPOS=()

for repo in $REPOS; do
    echo "--- $repo ---"
    REPO_DIR="$BASE_DIR/$repo"
    mkdir -p "$REPO_DIR"

    # Call the per-repo data script with custom output dir
    "$SCRIPT_DIR/weekly-report-data.sh" "$DAYS" "$ORG/$repo" "$REPO_DIR" 2>"$REPO_DIR/errors.log" || true

    # Handle repos with issues disabled (files may be empty or missing)
    for f in merged-prs open-prs open-issues new-issues ci-runs ci-runs-all; do
        if [ ! -f "$REPO_DIR/$f.json" ] || [ ! -s "$REPO_DIR/$f.json" ]; then
            echo '[]' > "$REPO_DIR/$f.json"
        fi
    done

    # Classify: active if any merged PR or new issue
    MERGED=$(jq length "$REPO_DIR/merged-prs.json")
    NEW_ISSUES=$(jq length "$REPO_DIR/new-issues.json")

    if [ "$MERGED" -gt 0 ] || [ "$NEW_ISSUES" -gt 0 ]; then
        ACTIVE_REPOS+=("$repo")
    else
        QUIET_REPOS+=("$repo")
    fi

    echo ""
done

# Build org-summary.json
echo "=== Building org-summary.json ==="

SUMMARY="[]"
TOTAL_MERGED=0
TOTAL_OPEN_PRS=0
TOTAL_OPEN_ISSUES=0
TOTAL_NEW_ISSUES=0

for repo in $REPOS; do
    REPO_DIR="$BASE_DIR/$repo"
    MERGED=$(jq length "$REPO_DIR/merged-prs.json")
    OPEN_PRS=$(jq length "$REPO_DIR/open-prs.json")
    OPEN_ISSUES=$(jq length "$REPO_DIR/open-issues.json")
    NEW_ISSUES=$(jq length "$REPO_DIR/new-issues.json")
    CI_RUNS=$(jq length "$REPO_DIR/ci-runs.json")
    CI_PASS=$(jq '[.[] | select(.conclusion == "success")] | length' "$REPO_DIR/ci-runs.json")

    IS_ACTIVE="false"
    for a in "${ACTIVE_REPOS[@]}"; do
        if [ "$a" = "$repo" ]; then
            IS_ACTIVE="true"
            break
        fi
    done

    SUMMARY=$(echo "$SUMMARY" | jq --arg repo "$repo" \
        --argjson merged "$MERGED" \
        --argjson open_prs "$OPEN_PRS" \
        --argjson open_issues "$OPEN_ISSUES" \
        --argjson new_issues "$NEW_ISSUES" \
        --argjson ci_runs "$CI_RUNS" \
        --argjson ci_pass "$CI_PASS" \
        --argjson active "$IS_ACTIVE" \
        '. + [{
            repo: $repo,
            merged_prs: $merged,
            open_prs: $open_prs,
            open_issues: $open_issues,
            new_issues: $new_issues,
            ci_runs: $ci_runs,
            ci_pass: $ci_pass,
            active: $active
        }]')

    TOTAL_MERGED=$((TOTAL_MERGED + MERGED))
    TOTAL_OPEN_PRS=$((TOTAL_OPEN_PRS + OPEN_PRS))
    TOTAL_OPEN_ISSUES=$((TOTAL_OPEN_ISSUES + OPEN_ISSUES))
    TOTAL_NEW_ISSUES=$((TOTAL_NEW_ISSUES + NEW_ISSUES))
done

# Wrap with totals
FINAL=$(jq -n \
    --argjson repos "$SUMMARY" \
    --argjson total_merged "$TOTAL_MERGED" \
    --argjson total_open_prs "$TOTAL_OPEN_PRS" \
    --argjson total_open_issues "$TOTAL_OPEN_ISSUES" \
    --argjson total_new_issues "$TOTAL_NEW_ISSUES" \
    --argjson active_count "${#ACTIVE_REPOS[@]}" \
    --argjson quiet_count "${#QUIET_REPOS[@]}" \
    '{
        totals: {
            merged_prs: $total_merged,
            open_prs: $total_open_prs,
            open_issues: $total_open_issues,
            new_issues: $total_new_issues,
            active_repos: $active_count,
            quiet_repos: $quiet_count
        },
        repos: $repos
    }')

echo "$FINAL" > "$BASE_DIR/org-summary.json"

# Print summary table
echo ""
echo "=== Org Summary ==="
printf "%-30s %8s %8s %8s %8s %8s\n" "Repo" "Merged" "OpenPRs" "OpenIss" "NewIss" "Status"
printf "%-30s %8s %8s %8s %8s %8s\n" "------------------------------" "--------" "--------" "--------" "--------" "--------"

for repo in $REPOS; do
    REPO_DIR="$BASE_DIR/$repo"
    MERGED=$(jq length "$REPO_DIR/merged-prs.json")
    OPEN_PRS=$(jq length "$REPO_DIR/open-prs.json")
    OPEN_ISSUES=$(jq length "$REPO_DIR/open-issues.json")
    NEW_ISSUES=$(jq length "$REPO_DIR/new-issues.json")

    STATUS="quiet"
    for a in "${ACTIVE_REPOS[@]}"; do
        if [ "$a" = "$repo" ]; then
            STATUS="active"
            break
        fi
    done

    printf "%-30s %8d %8d %8d %8d %8s\n" "$repo" "$MERGED" "$OPEN_PRS" "$OPEN_ISSUES" "$NEW_ISSUES" "$STATUS"
done

printf "%-30s %8s %8s %8s %8s\n" "------------------------------" "--------" "--------" "--------" "--------"
printf "%-30s %8d %8d %8d %8d\n" "TOTAL" "$TOTAL_MERGED" "$TOTAL_OPEN_PRS" "$TOTAL_OPEN_ISSUES" "$TOTAL_NEW_ISSUES"

echo ""
echo "Active repos: ${ACTIVE_REPOS[*]:-none}"
echo "Quiet repos: ${QUIET_REPOS[*]:-none}"
echo ""
echo "Data saved to $BASE_DIR/"
echo "Summary: $BASE_DIR/org-summary.json"
