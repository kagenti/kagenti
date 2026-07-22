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

CHARTS_DIR="$REPO_ROOT/charts/rossoctl"
VALUES_FILE="$CHARTS_DIR/values.yaml"
CHART_FILE="$CHARTS_DIR/Chart.yaml"
TEMPLATES_DIR="$CHARTS_DIR/templates"

DEPS_CHARTS_DIR="$REPO_ROOT/charts/rossoctl-deps"
DEPS_VALUES_FILE="$DEPS_CHARTS_DIR/values.yaml"

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

# jq is required for safe JSON construction. Fail early with a clear message
# rather than producing broken output.
if ! command -v jq >/dev/null 2>&1; then
    echo "error: jq is required but not installed" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Finding accumulators
#
# Each finding is a single JSON object built with jq -n --arg (so strings
# containing quotes, backslashes, colons, etc. are escaped correctly).
#
# ERRORS_JSON, WARNINGS_JSON, OKS_JSON are each a comma-separated list of
# JSON objects. They are wrapped in [] at output time.
# ---------------------------------------------------------------------------

ERRORS_JSON=""
ERROR_COUNT=0

WARNINGS_JSON=""
WARNING_COUNT=0

OKS_JSON=""
OK_COUNT=0

add_error() {
    local file="$1"
    local line="$2"
    local issue="$3"
    local obj
    obj=$(jq -n \
        --arg file "$file" \
        --argjson line "$line" \
        --arg issue "$issue" \
        '{file: $file, line: $line, issue: $issue}')

    if [[ -n "$ERRORS_JSON" ]]; then
        ERRORS_JSON="${ERRORS_JSON},"
    fi
    ERRORS_JSON="${ERRORS_JSON}${obj}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
}

add_warning() {
    local file="$1"
    local issue="$2"
    local obj
    obj=$(jq -n \
        --arg file "$file" \
        --arg issue "$issue" \
        '{file: $file, issue: $issue}')

    if [[ -n "$WARNINGS_JSON" ]]; then
        WARNINGS_JSON="${WARNINGS_JSON},"
    fi
    WARNINGS_JSON="${WARNINGS_JSON}${obj}"
    WARNING_COUNT=$((WARNING_COUNT + 1))
}

add_ok() {
    local file="$1"
    local check="$2"
    local obj
    obj=$(jq -n \
        --arg file "$file" \
        --arg check "$check" \
        '{file: $file, check: $check}')

    if [[ -n "$OKS_JSON" ]]; then
        OKS_JSON="${OKS_JSON},"
    fi
    OKS_JSON="${OKS_JSON}${obj}"
    OK_COUNT=$((OK_COUNT + 1))
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Check whether a version string is considered unpinned. Unpinned means:
#   - empty
#   - literal "*" or "x"
#   - contains any semver-range metacharacter: > < ~ ^
#   - is a wildcard pattern like "1.*" or "1.x"
is_unpinned_version() {
    local version="$1"

    if [[ -z "$version" ]]; then
        return 0
    fi
    if [[ "$version" == "*" ]] || [[ "$version" == "x" ]]; then
        return 0
    fi
    if [[ "$version" == *"*"* ]]; then
        return 0
    fi
    case "$version" in
        *">"*|*"<"*|*"~"*|*"^"*) return 0 ;;
    esac

    return 1
}

# ---------------------------------------------------------------------------
# Check 1: No "tag: latest" in values.yaml
# ---------------------------------------------------------------------------

if [[ ! -f "$VALUES_FILE" ]]; then
    add_error "charts/rossoctl/values.yaml" 0 "file not found"
else
    matches=$(grep -Fn 'tag: latest' "$VALUES_FILE" || true)

    if [[ -z "$matches" ]]; then
        add_ok "charts/rossoctl/values.yaml" "no tag: latest found"
    else
        while IFS= read -r match; do
            if [[ -z "$match" ]]; then
                continue
            fi

            line_number="${match%%:*}"
            add_error "charts/rossoctl/values.yaml" "$line_number" "tag: latest"
        done <<< "$matches"
    fi
fi

# ---------------------------------------------------------------------------
# Check 2: No ":latest" in template files
#
# grep -rn output format: <filepath>:<line>:<content>. Content can contain
# any character including colons, so only split on the first two colons.
# ---------------------------------------------------------------------------

if [[ ! -d "$TEMPLATES_DIR" ]]; then
    add_error "charts/rossoctl/templates/" 0 "directory not found"
else
    matches=$(grep -rFn ':latest' "$TEMPLATES_DIR" || true)

    if [[ -z "$matches" ]]; then
        add_ok "charts/rossoctl/templates/" "no :latest found"
    else
        while IFS= read -r match; do
            if [[ -z "$match" ]]; then
                continue
            fi

            # Split on the FIRST colon (file path) and SECOND colon (line).
            filepath="${match%%:*}"
            rest="${match#*:}"
            line_number="${rest%%:*}"
            filename=$(basename "$filepath")

            add_error "charts/rossoctl/templates/${filename}" "$line_number" ":latest"
        done <<< "$matches"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3: All Chart.yaml dependency versions are pinned
#
# Parse the dependencies block by walking lines. Each dependency starts with
# "- name:" at 0 indentation (inside the "dependencies:" block). A dependency
# can contain any ordering of fields like name:, version:, repository:,
# condition:, alias:, etc. We collect the version of each dependency, not
# assuming it immediately follows name.
#
# If yq is available we prefer it — it's a real YAML parser and handles every
# edge case (quotes, block scalars, comments). The bash fallback is just for
# environments without yq.
# ---------------------------------------------------------------------------

parse_chart_dependencies_with_yq() {
    # Use yq's `line` builtin to locate each dependency's position. yq emits
    # the line of the dependency map node; that's close enough (it points at
    # the first field of the item — usually "- name:" or the block start).
    #
    # Output format: "line<TAB>version" per dependency. Missing version
    # fields come back as empty strings.
    yq eval -r '.dependencies[] | [(. | line), (.version // "")] | @tsv' \
        "$CHART_FILE" 2>/dev/null
}

parse_chart_dependencies_with_bash() {
    # Walk Chart.yaml line-by-line, tracking whether we're inside the
    # "dependencies:" block. Each dependency starts with "- " and can contain
    # fields in any order (name, version, repository, condition, alias, etc).
    # We record the version and the line number it was found on, so the
    # caller can point at the exact offending line without a second grep.
    #
    # Output format: one "line_number<TAB>version" per dependency. A
    # dependency with no version emits "0<TAB>".
    local in_dependencies=false
    local current_version=""
    local current_version_line=0
    local have_item=false
    local line_number=0
    local line

    while IFS= read -r line || [[ -n "$line" ]]; do
        line_number=$((line_number + 1))

        # Top-level key (no leading whitespace, ends in colon). Entering or
        # leaving the dependencies block.
        if [[ "$line" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*: ]]; then
            # Flush the last item if we were in dependencies
            if [[ "$in_dependencies" == "true" ]] && [[ "$have_item" == "true" ]]; then
                printf '%d\t%s\n' "$current_version_line" "$current_version"
            fi

            if [[ "$line" == "dependencies:"* ]]; then
                in_dependencies=true
            else
                in_dependencies=false
            fi

            current_version=""
            current_version_line=0
            have_item=false
            continue
        fi

        if [[ "$in_dependencies" != "true" ]]; then
            continue
        fi

        # New dependency item (starts with "- " possibly with leading spaces).
        # Flush the previous item and reset state.
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]] ]]; then
            if [[ "$have_item" == "true" ]]; then
                printf '%d\t%s\n' "$current_version_line" "$current_version"
            fi

            current_version=""
            current_version_line=0
            have_item=true

            # The "- " line may include the first field (e.g. "- name: foo"
            # or "- version: 1.2.3"). Strip the "- " prefix so the same
            # field-match logic below applies.
            line="${line#*- }"
        fi

        # Look for "version:" on this line (with any indentation).
        if [[ "$line" =~ ^[[:space:]]*version:[[:space:]]*(.*)$ ]]; then
            local raw="${BASH_REMATCH[1]}"
            # Strip trailing comments, surrounding whitespace and quotes.
            raw="${raw%%#*}"
            raw="${raw## }"
            raw="${raw%% }"
            raw="${raw#\"}"
            raw="${raw%\"}"
            raw="${raw#\'}"
            raw="${raw%\'}"
            current_version="$raw"
            current_version_line="$line_number"
        fi
    done < "$CHART_FILE"

    # Flush the final item
    if [[ "$in_dependencies" == "true" ]] && [[ "$have_item" == "true" ]]; then
        printf '%d\t%s\n' "$current_version_line" "$current_version"
    fi
}

if [[ ! -f "$CHART_FILE" ]]; then
    add_error "charts/rossoctl/Chart.yaml" 0 "file not found"
else
    if command -v yq >/dev/null 2>&1; then
        dep_entries=$(parse_chart_dependencies_with_yq || true)
    else
        dep_entries=$(parse_chart_dependencies_with_bash || true)
    fi

    deps_ok=true

    if [[ -n "$dep_entries" ]]; then
        while IFS=$'\t' read -r line_number version; do
            # Trim leading/trailing whitespace
            version="${version## }"
            version="${version%% }"

            if is_unpinned_version "$version"; then
                deps_ok=false

                if [[ -z "$version" ]]; then
                    issue="unpinned dependency version: (empty)"
                else
                    issue="unpinned dependency version: ${version}"
                fi

                add_error "charts/rossoctl/Chart.yaml" "${line_number:-0}" "$issue"
            fi
        done <<< "$dep_entries"
    fi

    if [[ "$deps_ok" == "true" ]]; then
        add_ok "charts/rossoctl/Chart.yaml" "all dependency versions pinned"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3b: Chart.yaml version and appVersion match image tags
#
# The chart version and appVersion should be consistent with the pinned image
# tags. If image tags are pinned to e.g. v0.6.0-rc.11, the chart version and
# appVersion should be 0.6.0-rc.11 (without the 'v' prefix).
# ---------------------------------------------------------------------------

if [[ -f "$CHART_FILE" ]] && [[ -f "$VALUES_FILE" ]]; then
    if ! command -v yq >/dev/null 2>&1; then
        add_warning "charts/rossoctl/Chart.yaml" \
            "yq not found — skipping Chart.yaml version/appVersion consistency check"
    else
        chart_version=$(yq eval '.version' "$CHART_FILE" 2>/dev/null || echo "")
        chart_app_version=$(yq eval '.appVersion' "$CHART_FILE" 2>/dev/null || echo "")
        platform_tag=$(yq eval '.ui.frontend.tag' "$VALUES_FILE" 2>/dev/null || echo "")

        # Strip 'v' prefix from platform tag for comparison
        platform_tag_stripped="${platform_tag#v}"

        if [[ -n "$platform_tag_stripped" ]] && [[ "$platform_tag_stripped" != "null" ]]; then
            if [[ "$chart_version" != "$platform_tag_stripped" ]]; then
                add_error "charts/rossoctl/Chart.yaml" 0 \
                    "version ($chart_version) does not match image tags ($platform_tag_stripped) — run scripts/pin-release-tags.sh"
            else
                add_ok "charts/rossoctl/Chart.yaml" "version ($chart_version) matches image tags"
            fi

            if [[ "$chart_app_version" != "$platform_tag_stripped" ]]; then
                add_error "charts/rossoctl/Chart.yaml" 0 \
                    "appVersion ($chart_app_version) does not match image tags ($platform_tag_stripped) — run scripts/pin-release-tags.sh"
            else
                add_ok "charts/rossoctl/Chart.yaml" "appVersion ($chart_app_version) matches image tags"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Check 4 (soft warning): Chart.lock exists
# ---------------------------------------------------------------------------

if [[ -f "$CHARTS_DIR/Chart.lock" ]]; then
    add_ok "charts/rossoctl/Chart.lock" "present"
else
    add_warning "charts/rossoctl/Chart.lock" \
        "not found — run helm dependency update if you have local dependencies"
fi

# ---------------------------------------------------------------------------
# Check 5: No "tag: latest" in rossoctl-deps values.yaml
# ---------------------------------------------------------------------------

if [[ ! -f "$DEPS_VALUES_FILE" ]]; then
    add_warning "charts/rossoctl-deps/values.yaml" "file not found (skipping)"
else
    matches=$(grep -Fn 'tag: latest' "$DEPS_VALUES_FILE" || true)

    if [[ -z "$matches" ]]; then
        add_ok "charts/rossoctl-deps/values.yaml" "no tag: latest found"
    else
        while IFS= read -r match; do
            if [[ -z "$match" ]]; then
                continue
            fi

            line_number="${match%%:*}"
            add_error "charts/rossoctl-deps/values.yaml" "$line_number" "tag: latest"
        done <<< "$matches"
    fi
fi

# ---------------------------------------------------------------------------
# Check 6: rossoctl-deps images built by this repo are pinned consistently
#
# The spiffe-idp-setup image lives in rossoctl-deps but is built by this repo.
# Its tag must not drift from the main chart's platform image tags.
# ---------------------------------------------------------------------------

if [[ -f "$DEPS_VALUES_FILE" ]]; then
    if ! command -v yq >/dev/null 2>&1; then
        add_warning "charts/rossoctl-deps/values.yaml" \
            "yq not found — skipping spiffeIdp tag consistency check"
    else
        spiffe_tag=$(yq eval '.spiffeIdp.image.tag' "$DEPS_VALUES_FILE" 2>/dev/null || echo "")

        if [[ -n "$spiffe_tag" ]] && [[ "$spiffe_tag" != "null" ]]; then
            # Compare against the first platform image tag in the main chart
            platform_tag=$(yq eval '.ui.frontend.tag' "$VALUES_FILE" 2>/dev/null || echo "")

            if [[ -n "$platform_tag" ]] && [[ "$platform_tag" != "null" ]] \
               && [[ "$spiffe_tag" != "$platform_tag" ]]; then
                add_error "charts/rossoctl-deps/values.yaml" 0 \
                    "spiffeIdp.image.tag ($spiffe_tag) differs from platform tag ($platform_tag) — run scripts/pin-release-tags.sh"
            else
                add_ok "charts/rossoctl-deps/values.yaml" \
                    "spiffeIdp.image.tag ($spiffe_tag) consistent with platform"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Check 7 (optional): Verify pinned GHCR images exist in registry
#
# Extract image: <ref> lines from values.yaml. Only GHCR is checked.
# docker is required in this mode; fail with a clear message if missing.
# ---------------------------------------------------------------------------

if [[ "$VERIFY_IMAGES" == "true" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "error: --verify-images requires docker, which is not installed" >&2
        exit 2
    fi

    image_lines=$(grep -E '^[[:space:]]+image:[[:space:]]' "$VALUES_FILE" || true)

    if [[ -n "$image_lines" ]]; then
        while IFS= read -r image_line; do
            if [[ -z "$image_line" ]]; then
                continue
            fi

            # Take everything after the first "image:" occurrence.
            image="${image_line#*image:}"

            # Strip whitespace and quotes.
            image="${image## }"
            image="${image%% }"
            image="${image#\"}"
            image="${image%\"}"
            image="${image#\'}"
            image="${image%\'}"

            if [[ "$image" != ghcr.io/* ]]; then
                continue
            fi

            if docker manifest inspect "$image" >/dev/null 2>&1; then
                add_ok "image-verify" "${image} exists"
            else
                add_error "image-verify" 0 "image not found in registry: ${image}"
            fi
        done <<< "$image_lines"
    fi
fi

# ---------------------------------------------------------------------------
# Output results
# ---------------------------------------------------------------------------

ready=true
if [[ $ERROR_COUNT -gt 0 ]]; then
    ready=false
fi

if [[ "$JSON_MODE" == "true" ]]; then
    # Build the full response once via jq so it's guaranteed valid JSON.
    jq -n \
        --argjson errors "[${ERRORS_JSON}]" \
        --argjson warnings "[${WARNINGS_JSON}]" \
        --argjson oks "[${OKS_JSON}]" \
        --argjson error_count "$ERROR_COUNT" \
        --argjson warning_count "$WARNING_COUNT" \
        --argjson ready "$ready" \
        '{
            errors: $errors,
            warnings: $warnings,
            ok: $oks,
            summary: {errors: $error_count, warnings: $warning_count, ready: $ready}
        }'
else
    # Use $'...' so bash expands the escape sequences at assignment time,
    # not when printf interprets its format string. That way the printf
    # format strings below can be plain constants (shellcheck SC2059).
    RED=$'\033[0;31m'
    YELLOW=$'\033[0;33m'
    GREEN=$'\033[0;32m'
    NC=$'\033[0m'

    # Render findings by reading back the JSON arrays. Using jq + @tsv here
    # (rather than re-parsing the original input ourselves) means the output
    # always agrees with the JSON mode and correctly handles special
    # characters in file paths or issue strings.

    # Print errors
    if [[ "$ERROR_COUNT" -gt 0 ]]; then
        while IFS=$'\t' read -r file line issue; do
            printf '%s[FAIL]%s %s:%s    %s\n' "$RED" "$NC" "$file" "$line" "$issue"
        done < <(jq -r '.[] | [.file, (.line | tostring), .issue] | @tsv' \
                  <<< "[${ERRORS_JSON}]")
    fi

    # Print successes
    if [[ "$OK_COUNT" -gt 0 ]]; then
        while IFS=$'\t' read -r file check; do
            printf '%s[OK]%s   %s — %s\n' "$GREEN" "$NC" "$file" "$check"
        done < <(jq -r '.[] | [.file, .check] | @tsv' \
                  <<< "[${OKS_JSON}]")
    fi

    # Print warnings
    if [[ "$WARNING_COUNT" -gt 0 ]]; then
        while IFS=$'\t' read -r file issue; do
            printf '%s[WARN]%s %s — %s\n' "$YELLOW" "$NC" "$file" "$issue"
        done < <(jq -r '.[] | [.file, .issue] | @tsv' \
                  <<< "[${WARNINGS_JSON}]")
    fi

    echo ""
    if [[ "$ready" == "true" ]]; then
        printf '%sAll checks passed — release is ready to tag%s\n' "$GREEN" "$NC"
    else
        printf '%s%d error(s) found — release is NOT ready to tag%s\n' \
            "$RED" "$ERROR_COUNT" "$NC"
    fi
fi

if [[ "$ready" == "true" ]]; then
    exit 0
else
    exit 1
fi
