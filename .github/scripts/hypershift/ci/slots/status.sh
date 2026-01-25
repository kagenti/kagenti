#!/usr/bin/env bash
# .github/scripts/hypershift/ci/slots/status.sh
#
# Shows current CI slot status - who holds what slots.
# Useful for debugging and monitoring.
#
# Usage: status.sh [--watch]
#   --watch: Continuously refresh status every 10 seconds

set -uo pipefail

NAMESPACE="clusters"
LEASE_PREFIX="kagenti-ci-slot"
MAX_SLOTS="${MAX_SLOTS:-6}"  # Show up to 6 slots by default
WATCH_MODE=false

for arg in "$@"; do
    case $arg in
        --watch|-w)
            WATCH_MODE=true
            ;;
    esac
done

# Cross-platform date parsing
parse_iso_date() {
    local iso_date="$1"
    if [[ "$(uname)" == "Darwin" ]]; then
        date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%s 2>/dev/null || echo "0"
    else
        date -d "$iso_date" +%s 2>/dev/null || echo "0"
    fi
}

format_duration() {
    local seconds=$1
    if [[ $seconds -lt 60 ]]; then
        echo "${seconds}s"
    elif [[ $seconds -lt 3600 ]]; then
        echo "$((seconds / 60))m"
    else
        echo "$((seconds / 3600))h $((seconds % 3600 / 60))m"
    fi
}

show_status() {
    local now_epoch
    now_epoch=$(date +%s)

    echo "╔════════════════════════════════════════════════════════════════════════╗"
    echo "║                        CI Slot Status                                   ║"
    echo "╠════════════════════════════════════════════════════════════════════════╣"
    printf "║ %-8s │ %-8s │ %-25s │ %-12s ║\n" "Slot" "Status" "Holder" "Age"
    echo "╠════════════════════════════════════════════════════════════════════════╣"

    local occupied=0
    local available=0

    for slot in $(seq 0 $((MAX_SLOTS - 1))); do
        local lease_name="${LEASE_PREFIX}-${slot}"
        local info
        info=$(oc get lease "$lease_name" -n "$NAMESPACE" \
            -o jsonpath='{.spec.holderIdentity}|{.spec.acquireTime}|{.spec.leaseDurationSeconds}' 2>/dev/null || echo "")

        if [[ -z "$info" ]]; then
            printf "║ %-8s │ \033[32m%-8s\033[0m │ %-25s │ %-12s ║\n" "slot-$slot" "FREE" "-" "-"
            ((available++))
        else
            local holder acquire_time duration
            holder=$(echo "$info" | cut -d'|' -f1 | cut -c1-25)
            acquire_time=$(echo "$info" | cut -d'|' -f2)
            duration=$(echo "$info" | cut -d'|' -f3)

            local acquire_epoch age age_str status_color status_text
            acquire_epoch=$(parse_iso_date "$acquire_time")
            age=$((now_epoch - acquire_epoch))
            age_str=$(format_duration "$age")

            # Check if expired
            if [[ $age -gt ${duration:-7200} ]]; then
                status_color="\033[31m"  # Red
                status_text="EXPIRED"
            else
                status_color="\033[33m"  # Yellow
                status_text="OCCUPIED"
            fi

            printf "║ %-8s │ ${status_color}%-8s\033[0m │ %-25s │ %-12s ║\n" \
                "slot-$slot" "$status_text" "$holder" "$age_str"
            ((occupied++))
        fi
    done

    echo "╠════════════════════════════════════════════════════════════════════════╣"
    printf "║ Summary: %d occupied, %d available (max: %d)                           ║\n" \
        "$occupied" "$available" "$MAX_SLOTS"
    echo "╚════════════════════════════════════════════════════════════════════════╝"

    # Show HostedClusters if any
    echo ""
    echo "HostedClusters in 'clusters' namespace:"
    oc get hostedclusters -n clusters --no-headers 2>/dev/null | while read -r line; do
        echo "  $line"
    done || echo "  (none)"
}

if [[ "$WATCH_MODE" == "true" ]]; then
    while true; do
        clear
        show_status
        echo ""
        echo "Refreshing every 10s... (Ctrl+C to exit)"
        sleep 10
    done
else
    show_status
fi
