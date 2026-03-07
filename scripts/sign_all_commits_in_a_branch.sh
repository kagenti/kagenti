#!/usr/bin/env bash
#
# Sign all commits in current branch that are ahead of the tracked upstream.
# This adds both sign-off (-s) and GPG signature (-S) to each commit.
# Also rewrites Co-Authored-By trailers to:
#   Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>
#
# Usage: ./scripts/sign_all_commits_in_a_branch.sh [upstream-ref]
#
# If upstream-ref is not provided, uses the branch's tracked upstream,
# falling back to upstream/main if not set.
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the upstream reference
if [ $# -ge 1 ]; then
    UPSTREAM_REF="$1"
else
    # Try to get the tracked upstream branch
    UPSTREAM_REF=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo "")
    if [ -z "$UPSTREAM_REF" ]; then
        UPSTREAM_REF="upstream/main"
        echo -e "${YELLOW}No tracking branch set, using default: ${UPSTREAM_REF}${NC}"
    fi
fi

# Verify the upstream ref exists
if ! git rev-parse --verify "$UPSTREAM_REF" >/dev/null 2>&1; then
    echo -e "${RED}Error: Upstream reference '$UPSTREAM_REF' not found${NC}"
    echo "Try: git fetch upstream"
    exit 1
fi

# Count commits ahead of upstream
COMMIT_COUNT=$(git rev-list --count "$UPSTREAM_REF"..HEAD)

if [ "$COMMIT_COUNT" -eq 0 ]; then
    echo -e "${GREEN}No commits ahead of ${UPSTREAM_REF}. Nothing to sign.${NC}"
    exit 0
fi

# Get current branch name
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Show info
echo ""
echo -e "${BLUE}Branch:${NC} $CURRENT_BRANCH"
echo -e "${BLUE}Upstream:${NC} $UPSTREAM_REF"
echo -e "${BLUE}Commits to sign:${NC} $COMMIT_COUNT"
echo ""

# Show the commits that will be signed (no pager)
echo -e "${YELLOW}Commits that will be signed:${NC}"
git --no-pager log --oneline "$UPSTREAM_REF"..HEAD
echo ""

# Check for Co-Authored-By trailers that will be rewritten
COAUTH_COUNT=$(git --no-pager log --format='%B' "$UPSTREAM_REF"..HEAD | grep -ci "co-authored-by" || true)
if [ "$COAUTH_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}Found $COAUTH_COUNT Co-Authored-By lines — will rewrite to:${NC}"
    echo -e "  Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
    echo ""
fi

# Show the command that will be run (non-interactive rebase with exec)
echo -e "${GREEN}Will run: rebase with sign-off, GPG sign, and trailer rewrite${NC}"
echo ""

# Prompt for confirmation
echo -ne "${YELLOW}Run this command? [y/N]: ${NC}"
read -r REPLY

if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo -e "${RED}Cancelled.${NC}"
    exit 0
fi

# Run the rebase (non-interactive)
# Each commit: rewrite Co-Authored-By trailers, then amend with sign-off and GPG
echo ""
echo -e "${BLUE}Running rebase to sign commits and rewrite trailers...${NC}"
echo ""

ASSISTED_BY="Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"

git rebase "HEAD~${COMMIT_COUNT}" --exec '
MSG=$(git log -1 --format="%B")
if echo "$MSG" | grep -qi "co-authored-by"; then
    NEW_MSG=$(echo "$MSG" | sed -E "/^[Cc]o-[Aa]uthored-[Bb]y:.*/d" | sed -e :a -e "/^\n*$/{$d;N;ba;}")
    NEW_MSG="$NEW_MSG

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
    git commit --amend -s -S -m "$NEW_MSG" --no-edit 2>/dev/null || git commit --amend -s -m "$NEW_MSG" --no-edit
else
    git commit --amend -s -S --no-edit 2>/dev/null || git commit --amend -s --no-edit
fi
'

echo ""
echo -e "${GREEN}Done! All $COMMIT_COUNT commits have been signed.${NC}"
echo ""
echo "You may need to force-push:"
echo "  git push origin $CURRENT_BRANCH --force-with-lease"
