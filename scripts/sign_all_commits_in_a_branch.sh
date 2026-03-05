#!/usr/bin/env bash
#
# Sign all commits in current branch that are ahead of upstream/main.
# This adds both sign-off (-s) and GPG signature (-S) to each commit,
# and replaces any Co-Authored-By trailers with Assisted-By.
#
# Usage: ./scripts/sign_all_commits_in_a_branch.sh [upstream-ref]
#
# Default upstream-ref: upstream/main
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the upstream reference (default: upstream/main)
UPSTREAM_REF="${1:-upstream/main}"

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

# Trailer replacement
ASSISTED_BY="Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"

# Show info
echo ""
echo -e "${BLUE}Branch:${NC} $CURRENT_BRANCH"
echo -e "${BLUE}Upstream:${NC} $UPSTREAM_REF"
echo -e "${BLUE}Commits to sign:${NC} $COMMIT_COUNT"
echo ""
echo -e "${YELLOW}Commits that will be signed:${NC}"
git --no-pager log --oneline "$UPSTREAM_REF"..HEAD
echo ""
echo -e "${GREEN}Will sign each commit and replace Co-Authored-By trailers with:${NC}"
echo "  $ASSISTED_BY"
echo ""

# Prompt for confirmation
echo -ne "${YELLOW}Run this? [y/N]: ${NC}"
read -r REPLY

if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo -e "${RED}Cancelled.${NC}"
    exit 0
fi

# Step 1: Replace Co-Authored-By trailers using filter-branch --msg-filter
HAS_COAUTHOR=$(git log --format="%B" "$UPSTREAM_REF"..HEAD | grep -ciE '^Co-[Aa]uthored-[Bb]y:' || true)

if [ "$HAS_COAUTHOR" -gt 0 ]; then
    echo ""
    echo -e "${BLUE}Step 1/2: Replacing $HAS_COAUTHOR Co-Authored-By trailer(s)...${NC}"
    FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
        --msg-filter "sed -E '/^[Cc]o-[Aa]uthored-[Bb]y:.*/d' | awk 'NF{p=1}p'; echo '$ASSISTED_BY'" \
        "$UPSTREAM_REF"..HEAD
else
    echo ""
    echo -e "${GREEN}Step 1/2: No Co-Authored-By trailers found, skipping.${NC}"
fi

# Step 2: Sign all commits (after message rewriting, so signatures stick)
# Re-count in case filter-branch changed the range
COMMIT_COUNT=$(git rev-list --count "$UPSTREAM_REF"..HEAD)
echo ""
echo -e "${BLUE}Step 2/2: Signing $COMMIT_COUNT commits...${NC}"
git rebase "HEAD~${COMMIT_COUNT}" \
    --exec 'git commit --amend --no-verify --no-edit -s -S'

echo ""
echo -e "${GREEN}Done! All $COMMIT_COUNT commits have been signed and trailers updated.${NC}"
echo ""
echo "You may need to force-push:"
echo "  git push origin $CURRENT_BRANCH --force-with-lease"
