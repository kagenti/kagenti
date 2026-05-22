#!/usr/bin/env bash
# Gather weekly report data from GitHub API
# Usage: ./weekly-report-data.sh [days] [repo] [outdir]
# Output: JSON files in /tmp/kagenti/github/data/

set -euo pipefail

DAYS="${1:-7}"
REPO="${2:-kagenti/kagenti}"
OUTDIR="${3:-/tmp/kagenti/github/data}"
mkdir -p "$OUTDIR"

SINCE=$(date -v-${DAYS}d -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -d "${DAYS} days ago" -u +"%Y-%m-%dT%H:%M:%SZ")

echo "=== Gathering data for $REPO (last $DAYS days, since $SINCE) ==="

echo "  Merged PRs..."
gh pr list --repo "$REPO" --state merged --limit 100 \
  --json number,title,author,mergedAt,labels,changedFiles \
  --jq "[.[] | select(.mergedAt > \"$SINCE\")]" \
  > "$OUTDIR/merged-prs.json"

echo "  Open PRs..."
gh pr list --repo "$REPO" --state open --limit 100 \
  --json number,title,author,createdAt,updatedAt,reviewDecision,mergeable,labels,body,changedFiles,isDraft \
  > "$OUTDIR/open-prs.json"

echo "  Open issues..."
gh issue list --repo "$REPO" --state open --limit 200 \
  --json number,title,author,createdAt,updatedAt,labels,assignees,comments,body \
  > "$OUTDIR/open-issues.json"

echo "  New issues (last ${DAYS} days)..."
gh issue list --repo "$REPO" --state all --limit 100 \
  --json number,title,author,createdAt,updatedAt,labels,state \
  --jq "[.[] | select(.createdAt > \"$SINCE\")]" \
  > "$OUTDIR/new-issues.json"

echo "  CI runs on main..."
gh run list --repo "$REPO" --branch main --limit 30 \
  --json databaseId,conclusion,name,createdAt,headSha,displayTitle \
  > "$OUTDIR/ci-runs.json"

echo "  CI runs (all, for PR checks)..."
gh run list --repo "$REPO" --limit 50 \
  --json databaseId,conclusion,name,createdAt,headSha,displayTitle \
  > "$OUTDIR/ci-runs-all.json"

echo ""
echo "=== Summary ==="
echo "  Merged PRs:  $(jq length "$OUTDIR/merged-prs.json")"
echo "  Open PRs:    $(jq length "$OUTDIR/open-prs.json") ($(jq '[.[] | select(.isDraft)] | length' "$OUTDIR/open-prs.json") draft)"
echo "  Open issues: $(jq length "$OUTDIR/open-issues.json")"
echo "  New issues:  $(jq length "$OUTDIR/new-issues.json")"
echo "  CI runs:     $(jq length "$OUTDIR/ci-runs.json")"
echo ""
echo "Data saved to $OUTDIR/"
