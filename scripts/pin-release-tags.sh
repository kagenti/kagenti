#!/usr/bin/env bash
#
# pin-release-tags.sh — Pin all kagenti-built image tags to a release version.
#
# Updates image tags across both charts/kagenti/ and charts/kagenti-deps/ so
# that a tagged release checkout always pulls the correct images when installed
# from source (via the setup-kagenti.sh installers).
#
# Usage:
#   ./scripts/pin-release-tags.sh v0.6.0-rc.6
#   ./scripts/pin-release-tags.sh v0.7.0-alpha.2 --dry-run
#   ./scripts/pin-release-tags.sh v0.6.0 --verify-images
#
# This script is idempotent — running it multiple times with the same version
# produces the same result.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

KAGENTI_VALUES="$REPO_ROOT/charts/kagenti/values.yaml"
KAGENTI_DEPS_VALUES="$REPO_ROOT/charts/kagenti-deps/values.yaml"
# Only kagenti Chart.yaml is versioned here; kagenti-deps is a dependency chart
# whose version is managed independently via its own release cadence.
KAGENTI_CHART="$REPO_ROOT/charts/kagenti/Chart.yaml"

DRY_RUN=false
VERIFY_IMAGES=false

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $(basename "$0") VERSION [OPTIONS]

Pin all kagenti-built container image tags to VERSION across both Helm charts.

Arguments:
  VERSION             The release version tag (e.g., v0.6.0-rc.6, v0.7.0-alpha.1)

Options:
  --dry-run              Show what would change without modifying files
  --verify-images        Check that images exist in ghcr.io before pinning
  --chart-version V      Override Chart.yaml version (default: derived from VERSION)
  --skip-chart-version   Do NOT update Chart.yaml version/appVersion
  -h, --help             Show this help message

Images pinned (charts/kagenti/values.yaml):
  - ui.frontend.tag
  - ui.backend.tag
  - uiOAuthSecret.tag
  - agentOAuthSecret.tag
  - apiOAuthSecret.tag
  - mlflowOAuthSecret.tag

Images pinned (charts/kagenti-deps/values.yaml):
  - spiffeIdp.image.tag

EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

VERSION=""
CHART_VERSION=""
SKIP_CHART_VERSION=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)             DRY_RUN=true; shift ;;
        --verify-images)       VERIFY_IMAGES=true; shift ;;
        --chart-version)       CHART_VERSION="$2"; shift 2 ;;
        --skip-chart-version)  SKIP_CHART_VERSION=true; shift ;;
        -h|--help)             usage ;;
        -*)                    echo "Unknown option: $1" >&2; usage ;;
        *)
            if [[ -z "$VERSION" ]]; then
                VERSION="$1"
            else
                echo "Unexpected argument: $1" >&2; usage
            fi
            shift
            ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    echo "error: VERSION argument is required" >&2
    echo "" >&2
    usage
fi

# Validate version format (must start with v and contain at least major.minor.patch)
if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
    echo "error: VERSION must match vX.Y.Z[-prerelease] (got: $VERSION)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------

if ! command -v yq >/dev/null 2>&1; then
    echo "error: yq is required but not installed" >&2
    echo "  Install: brew install yq  (or see https://github.com/mikefarah/yq)" >&2
    exit 2
fi

if [[ ! -f "$KAGENTI_VALUES" ]]; then
    echo "error: $KAGENTI_VALUES not found (run from repo root)" >&2
    exit 1
fi

if [[ ! -f "$KAGENTI_DEPS_VALUES" ]]; then
    echo "error: $KAGENTI_DEPS_VALUES not found (run from repo root)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Image registry and paths
# ---------------------------------------------------------------------------

REGISTRY="ghcr.io/kagenti/kagenti"

# Map of yq paths to image names. These are ALL images built by this repo's
# build.yaml CI workflow and must be kept in sync with the matrix there.
#
# Format: "values-file|yq-path|image-name"
PINNABLE_IMAGES=(
    "$KAGENTI_VALUES|.ui.frontend.tag|ui-v2"
    "$KAGENTI_VALUES|.ui.backend.tag|backend"
    "$KAGENTI_VALUES|.uiOAuthSecret.tag|ui-oauth-secret"
    "$KAGENTI_VALUES|.agentOAuthSecret.tag|agent-oauth-secret"
    "$KAGENTI_VALUES|.apiOAuthSecret.tag|api-oauth-secret"
    "$KAGENTI_VALUES|.mlflowOAuthSecret.tag|mlflow-oauth-secret"
    "$KAGENTI_DEPS_VALUES|.spiffeIdp.image.tag|spiffe-idp-setup"
)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; NC=''
fi

# ---------------------------------------------------------------------------
# Verify images exist (optional)
# ---------------------------------------------------------------------------

if [[ "$VERIFY_IMAGES" == "true" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "error: --verify-images requires docker" >&2
        exit 2
    fi

    echo "Verifying images exist in registry..."
    all_found=true

    for entry in "${PINNABLE_IMAGES[@]}"; do
        IFS='|' read -r _ _ image_name <<< "$entry"
        full_ref="$REGISTRY/$image_name:$VERSION"

        if docker manifest inspect "$full_ref" >/dev/null 2>&1; then
            printf '%s[OK]%s   %s\n' "$GREEN" "$NC" "$full_ref"
        else
            printf '%s[MISS]%s %s\n' "$RED" "$NC" "$full_ref"
            all_found=false
        fi
    done

    if [[ "$all_found" != "true" ]]; then
        echo ""
        echo "${RED}error: Some images are missing. Build and push them before pinning.${NC}" >&2
        exit 1
    fi

    echo ""
fi

# ---------------------------------------------------------------------------
# Pin image tags
# ---------------------------------------------------------------------------

echo "Pinning image tags to ${VERSION}..."
echo ""

for entry in "${PINNABLE_IMAGES[@]}"; do
    IFS='|' read -r target_file yq_path image_name <<< "$entry"

    # Get current value (yq returns literal "null" for missing paths)
    current=$(yq eval "$yq_path // \"\"" "$target_file")
    rel_path="${target_file#$REPO_ROOT/}"

    if [[ -z "$current" ]]; then
        echo "error: yq path $yq_path not found in $rel_path" >&2
        exit 1
    fi

    if [[ "$current" == "$VERSION" ]]; then
        printf '%s[SKIP]%s %s (%s) — already %s\n' "$GREEN" "$NC" "$image_name" "$rel_path" "$VERSION"
        continue
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        printf '%s[DRY]%s  %s (%s): %s → %s\n' "$YELLOW" "$NC" "$image_name" "$rel_path" "$current" "$VERSION"
    else
        yq eval --arg v "$VERSION" "$yq_path = \$v" -i "$target_file"
        printf '%s[PIN]%s  %s (%s): %s → %s\n' "$GREEN" "$NC" "$image_name" "$rel_path" "$current" "$VERSION"
    fi
done

# ---------------------------------------------------------------------------
# Pin Chart.yaml version
#
# By default, Chart.yaml version and appVersion are set to match VERSION
# (strip 'v' prefix). Use --chart-version to override, or --skip-chart-version
# to leave Chart.yaml untouched.
# ---------------------------------------------------------------------------

if [[ "$SKIP_CHART_VERSION" != "true" ]]; then
    # Default to VERSION if --chart-version was not explicitly passed
    if [[ -z "$CHART_VERSION" ]]; then
        CHART_VERSION="$VERSION"
    fi

    echo ""
    echo "Updating Chart.yaml version..."

    # Strip 'v' prefix for chart version
    chart_ver="${CHART_VERSION#v}"

    if [[ "$DRY_RUN" == "true" ]]; then
        current_chart_ver=$(yq eval '.version' "$KAGENTI_CHART")
        printf '%s[DRY]%s  Chart.yaml version: %s → %s\n' "$YELLOW" "$NC" "$current_chart_ver" "$chart_ver"
        printf '%s[DRY]%s  Chart.yaml appVersion: → %s\n' "$YELLOW" "$NC" "$chart_ver"
    else
        yq eval --arg v "$chart_ver" '.version = $v' -i "$KAGENTI_CHART"
        yq eval --arg v "$chart_ver" '.appVersion = $v' -i "$KAGENTI_CHART"
        printf '%s[PIN]%s  Chart.yaml version + appVersion → %s\n' "$GREEN" "$NC" "$chart_ver"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
    echo "${YELLOW}Dry run complete — no files were modified.${NC}"
    echo "Remove --dry-run to apply changes."
else
    echo "${GREEN}All image tags pinned to ${VERSION}.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review changes:  git diff charts/"
    echo "  2. Run validation:  bash scripts/check-release-pins.sh"
    echo "  3. Commit:          git add charts/ && git commit -s -m \"chore(release): pin image tags for ${VERSION}\""
fi
