#!/usr/bin/env bash
#
# Sign commits in specified worktrees and push.
# Runs scripts/sign_all_commits_in_a_branch.sh in each worktree.
#
# Usage:
#   ./scripts/sign_all_pr_worktrees.sh <worktree1> <worktree2> ...
#
# Examples:
#   # Sign a single PR worktree
#   ./scripts/sign_all_pr_worktrees.sh pr-feature-flags
#
#   # Sign multiple
#   ./scripts/sign_all_pr_worktrees.sh pr-k2-skills pr-k5-deploy pr-k6-types
#
#   # Sign all kagenti PR worktrees
#   ./scripts/sign_all_pr_worktrees.sh pr-k{1-infra,2-skills,3a-sessiondb,3b-routes,3c-sidecars,4-budget,5-deploy,6-types,6a-sandbox-ui,6b-graph,6c-support-ui,6d-pages,7-uitests,8-e2etests,10-cleanup} pr-feature-flags
#
#   # Sign agent-examples worktrees
#   ./scripts/sign_all_pr_worktrees.sh pr-a1-core pr-a2-tests pr-a3-config
#
#   # Sign stream1 integration branches
#   ./scripts/sign_all_pr_worktrees.sh stream1-sandbox-agent stream1-agent-examples
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIGN_SCRIPT="$REPO_ROOT/scripts/sign_all_commits_in_a_branch.sh"

if [ ! -x "$SIGN_SCRIPT" ]; then
    echo "Error: Sign script not found at $SIGN_SCRIPT"
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "Error: No worktrees specified."
    echo ""
    echo "Usage: $0 <worktree1> <worktree2> ..."
    echo ""
    echo "Available worktrees:"
    for d in "$REPO_ROOT/.worktrees"/{pr-*,stream*}; do
        [ -d "$d" ] && echo "  $(basename "$d")"
    done
    exit 1
fi

signed=0
skipped=0
failed=0

for wt in "$@"; do
    wt_path="$REPO_ROOT/.worktrees/$wt"
    if [ ! -d "$wt_path" ]; then
        echo "SKIP $wt — worktree not found at $wt_path"
        skipped=$((skipped + 1))
        continue
    fi

    branch=$(git -C "$wt_path" branch --show-current 2>/dev/null || echo "detached")
    count=$(git -C "$wt_path" log --oneline upstream/main..HEAD 2>/dev/null | wc -l | tr -d ' ')

    if [ "$count" -eq 0 ]; then
        echo "SKIP $wt — no commits ahead of upstream/main"
        skipped=$((skipped + 1))
        continue
    fi

    echo ""
    echo "--- $wt ($branch, $count commits) ---"
    if (cd "$wt_path" && "$SIGN_SCRIPT" upstream/main --no-gpg --yes); then
        # Push to upstream (org repo) — streaming PRs are created on upstream branches,
        # not fork branches, so reviewers can see them directly. This is an intentional
        # exception to the normal fork-based workflow.
        echo "Pushing $branch..."
        if git -C "$wt_path" push upstream "$branch" --force-with-lease 2>&1 | tail -1; then
            signed=$((signed + 1))
        else
            echo "WARN: push failed for $wt"
            failed=$((failed + 1))
        fi
    else
        echo "WARN: signing failed for $wt"
        failed=$((failed + 1))
    fi
done

echo ""
echo "=== Done: $signed signed+pushed, $skipped skipped, $failed failed ==="
