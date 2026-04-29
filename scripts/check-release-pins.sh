#!/usr/bin/env bash
#
# check-release-pins.sh — Validate that all image tags and chart dependencies
# are pinned before cutting a release tag.
#
# Exit 0 if all checks pass (release-ready).
# Exit 1 if any hard-fail check fails.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CHARTS_DIR="$REPO_ROOT/charts/kagenti"
VALUES_FILE="$CHARTS_DIR/values.yaml"
CHART_FILE="$CHARTS_DIR/Chart.yaml"
TEMPLATES_DIR="$CHARTS_DIR/templates"

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

JSON_MODE=false
VERIFY_IMAGES=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Validate that all image tags and chart dependencies are pinned for release.

Options:
  --json            Output results as JSON (for CI summary consumption)
  --verify-images   Check that pinned GHCR images exist via docker manifest inspect
  -h, --help        Show this help message
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json)           JSON_MODE=true;     shift ;;
        --verify-images)  VERIFY_IMAGES=true; shift ;;
        -h|--help)        usage ;;
        *)                echo "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Result accumulators (plain text lines, one per finding)
# ---------------------------------------------------------------------------

error_lines=""
error_count=0

warning_lines=""
warning_count=0

ok_lines=""
ok_count=0

# JSON accumulators (comma-separated JSON objects)
json_errors=""
json_warnings=""
json_oks=""

add_error() {
    local file="$1"
    local line="$2"
    local issue="$3"

    error_count=$((error_count + 1))
    error_lines="${error_lines}FAIL|${file}|${line}|${issue}"$'\n'

    if [[ -n "$json_errors" ]]; then
        json_errors="${json_errors},"
    fi
    json_errors="${json_errors}{\"file\": \"${file}\", \"line\": ${line}, \"issue\": \"${issue}\"}"
}

add_warning() {
    local file="$1"
    local issue="$2"

    warning_count=$((warning_count + 1))
    warning_lines="${warning_lines}WARN|${file}|${issue}"$'\n'

    if [[ -n "$json_warnings" ]]; then
        json_warnings="${json_warnings},"
    fi
    json_warnings="${json_warnings}{\"file\": \"${file}\", \"issue\": \"${issue}\"}"
}

add_ok() {
    local file="$1"
    local check="$2"

    ok_count=$((ok_count + 1))
    ok_lines="${ok_lines}OK|${file}|${check}"$'\n'

    if [[ -n "$json_oks" ]]; then
        json_oks="${json_oks},"
    fi
    json_oks="${json_oks}{\"file\": \"${file}\", \"check\": \"${check}\"}"
}

# ---------------------------------------------------------------------------
# Check 1: No "tag: latest" in values.yaml
# ---------------------------------------------------------------------------

if [[ ! -f "$VALUES_FILE" ]]; then
    add_error "charts/kagenti/values.yaml" 0 "file not found"
else
    matches=$(grep -n 'tag: latest' "$VALUES_FILE" || true)

    if [[ -z "$matches" ]]; then
        add_ok "charts/kagenti/values.yaml" "no tag: latest found"
    else
        while IFS= read -r match; do
            line_number=$(echo "$match" | cut -d: -f1)
            add_error "charts/kagenti/values.yaml" "$line_number" "tag: latest"
        done <<< "$matches"
    fi
fi

# ---------------------------------------------------------------------------
# Check 2: No ":latest" in template files
# ---------------------------------------------------------------------------

if [[ ! -d "$TEMPLATES_DIR" ]]; then
    add_error "charts/kagenti/templates/" 0 "directory not found"
else
    matches=$(grep -rn ':latest' "$TEMPLATES_DIR" || true)

    if [[ -z "$matches" ]]; then
        add_ok "charts/kagenti/templates/" "no :latest found"
    else
        while IFS= read -r match; do
            # match format: /full/path/to/file.yaml:95:    image: ...
            filepath=$(echo "$match" | cut -d: -f1)
            line_number=$(echo "$match" | cut -d: -f2)
            filename=$(basename "$filepath")
            add_error "charts/kagenti/templates/${filename}" "$line_number" ":latest"
        done <<< "$matches"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3: All Chart.yaml dependency versions are pinned
# ---------------------------------------------------------------------------

if [[ ! -f "$CHART_FILE" ]]; then
    add_error "charts/kagenti/Chart.yaml" 0 "file not found"
else
    # Extract dependency version lines (lines that follow "- name:" lines)
    dep_versions=$(grep -A1 '^\- name:' "$CHART_FILE" | grep 'version:' || true)
    deps_ok=true

    if [[ -n "$dep_versions" ]]; then
        while IFS= read -r version_line; do
            # Extract just the version value, stripping whitespace and quotes
            version=$(echo "$version_line" | cut -d: -f2 | tr -d ' "'"'"'')

            is_unpinned=false
            if [[ "$version" == "*" ]]; then
                is_unpinned=true
            fi
            if [[ "$version" == "" ]]; then
                is_unpinned=true
            fi
            if echo "$version" | grep -qE '[><~^]'; then
                is_unpinned=true
            fi

            if [[ "$is_unpinned" == "true" ]]; then
                deps_ok=false
                line_number=$(grep -n "version:.*${version}" "$CHART_FILE" | head -1 | cut -d: -f1)
                add_error "charts/kagenti/Chart.yaml" "${line_number:-0}" "unpinned dependency version: ${version}"
            fi
        done <<< "$dep_versions"
    fi

    if [[ "$deps_ok" == "true" ]]; then
        add_ok "charts/kagenti/Chart.yaml" "all dependency versions pinned"
    fi
fi

# ---------------------------------------------------------------------------
# Check 4 (soft warning): Chart.lock exists
# ---------------------------------------------------------------------------

if [[ -f "$CHARTS_DIR/Chart.lock" ]]; then
    add_ok "charts/kagenti/Chart.lock" "present"
else
    add_warning "charts/kagenti/Chart.lock" "not found — run helm dependency update if you have local dependencies"
fi

# ---------------------------------------------------------------------------
# Check 5 (optional): Verify pinned GHCR images exist in registry
# ---------------------------------------------------------------------------

if [[ "$VERIFY_IMAGES" == "true" ]]; then
    image_lines=$(grep -E '^\s+image:' "$VALUES_FILE" || true)

    if [[ -n "$image_lines" ]]; then
        while IFS= read -r image_line; do
            # Extract the image reference after "image:"
            image=$(echo "$image_line" | cut -d: -f2- | tr -d ' "'"'"'')

            # Only check GHCR images
            if [[ "$image" != ghcr.io/* ]]; then
                continue
            fi

            if docker manifest inspect "$image" >/dev/null 2>&1; then
                add_ok "image-verify" "$image exists"
            else
                add_error "image-verify" 0 "image not found in registry: $image"
            fi
        done <<< "$image_lines"
    fi
fi

# ---------------------------------------------------------------------------
# Output results
# ---------------------------------------------------------------------------

ready=true
if [[ $error_count -gt 0 ]]; then
    ready=false
fi

if [[ "$JSON_MODE" == "true" ]]; then
    cat <<EOF
{
  "errors": [${json_errors}],
  "warnings": [${json_warnings}],
  "ok": [${json_oks}],
  "summary": {"errors": ${error_count}, "warnings": ${warning_count}, "ready": ${ready}}
}
EOF
else
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    GREEN='\033[0;32m'
    NC='\033[0m'

    # Print errors
    if [[ -n "$error_lines" ]]; then
        while IFS='|' read -r _status file line issue; do
            if [[ -n "$file" ]]; then
                printf "${RED}[FAIL]${NC} %s:%s    %s\n" "$file" "$line" "$issue"
            fi
        done <<< "$error_lines"
    fi

    # Print successes
    if [[ -n "$ok_lines" ]]; then
        while IFS='|' read -r _status file check _rest; do
            if [[ -n "$file" ]]; then
                printf "${GREEN}[OK]${NC}   %s — %s\n" "$file" "$check"
            fi
        done <<< "$ok_lines"
    fi

    # Print warnings
    if [[ -n "$warning_lines" ]]; then
        while IFS='|' read -r _status file issue _rest; do
            if [[ -n "$file" ]]; then
                printf "${YELLOW}[WARN]${NC} %s — %s\n" "$file" "$issue"
            fi
        done <<< "$warning_lines"
    fi

    echo ""
    if [[ "$ready" == "true" ]]; then
        printf "${GREEN}All checks passed — release is ready to tag${NC}\n"
    else
        printf "${RED}%d error(s) found — release is NOT ready to tag${NC}\n" "$error_count"
    fi
fi

if [[ "$ready" == "true" ]]; then
    exit 0
else
    exit 1
fi
