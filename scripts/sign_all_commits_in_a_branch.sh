#!/usr/bin/env bash
#
# Sign all commits in current branch that are ahead of upstream/main.
# Adds sign-off (-s) and optionally GPG signature (-S) to each commit,
# and replaces any Co-Authored-By trailers with Assisted-By.
#
# Usage: ./scripts/sign_all_commits_in_a_branch.sh [upstream-ref] [--no-gpg] [--yes]
#
# Default upstream-ref: upstream/main
# --no-gpg: skip GPG signing (DCO sign-off only, no password prompt)
# --yes/-y: skip confirmation prompt (for automation)
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
GPG_SIGN="-S"
AUTO_YES=false
UPSTREAM_REF="upstream/main"
POSITIONAL_SET=false
for arg in "$@"; do
    case "$arg" in
        --no-gpg) GPG_SIGN="--no-gpg-sign" ;;
        --yes|-y) AUTO_YES=true ;;
        -*)
            echo -e "${RED}Error: Unknown flag '$arg'${NC}"
            echo "Usage: $0 [upstream-ref] [--no-gpg] [--yes]"
            exit 1
            ;;
        *)
            if [ "$POSITIONAL_SET" = "true" ]; then
                echo -e "${RED}Error: Only one positional argument (upstream-ref) allowed${NC}"
                echo "Usage: $0 [upstream-ref] [--no-gpg] [--yes]"
                exit 1
            fi
            UPSTREAM_REF="$arg"
            POSITIONAL_SET=true
            ;;
    esac
done

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

# Prompt for confirmation (skip with --yes/-y)
if [ "$AUTO_YES" = "true" ]; then
    REPLY="y"
else
    echo -ne "${YELLOW}Run this? [y/N]: ${NC}"
    read -r REPLY
fi

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
# --no-verify: safe here because we're amending existing commits (adding trailers),
# not creating new content. Pre-commit hooks would reject the amend due to unstaged changes.
git rebase "HEAD~${COMMIT_COUNT}" \
    --exec "git commit --amend --no-verify --no-edit -s $GPG_SIGN"

echo ""
echo -e "${GREEN}Done! All $COMMIT_COUNT commits have been signed and trailers updated.${NC}"
echo ""
echo "You may need to force-push:"
echo "  git push origin $CURRENT_BRANCH --force-with-lease"
