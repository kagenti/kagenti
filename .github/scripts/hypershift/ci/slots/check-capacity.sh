#!/usr/bin/env bash
# .github/scripts/hypershift/ci/slots/check-capacity.sh
#
# Checks if the management cluster has capacity for a new hosted cluster.
# Considers both current capacity AND potential autoscaled capacity.
#
# Exit 0: Sufficient capacity
# Exit 1: Insufficient capacity
#
# IMPORTANT: This checks for the WHOLE cluster's resources upfront
# to prevent half-deployed clusters stuck waiting for resources.

set -euo pipefail

# Resource requirements for a hosted cluster control plane
# Based on measurements from setup-autoscaling.sh
CLUSTER_CPU_REQ_M="${CLUSTER_CPU_REQ_M:-3800}"    # 3.8 cores in millicores
CLUSTER_MEM_REQ_MI="${CLUSTER_MEM_REQ_MI:-14848}" # 14.5 Gi in MiB

# Safety margin (10% buffer)
SAFETY_MARGIN="${SAFETY_MARGIN:-1.1}"

echo "Checking cluster capacity..."
echo ""

# Get autoscaler max nodes
get_max_autoscale_nodes() {
    local total_max=0
    local max_list
    max_list=$(oc get machineautoscaler -n openshift-machine-api \
        -o jsonpath='{.items[*].spec.maxReplicas}' 2>/dev/null || echo "")

    for max in $max_list; do
        total_max=$((total_max + max))
    done

    # If no autoscalers, return current node count
    if [[ $total_max -eq 0 ]]; then
        oc get nodes -l 'node-role.kubernetes.io/worker' --no-headers 2>/dev/null | wc -l | tr -d ' '
    else
        echo "$total_max"
    fi
}

# Get current worker node count
get_current_workers() {
    oc get nodes -l 'node-role.kubernetes.io/worker' --no-headers 2>/dev/null | wc -l | tr -d ' '
}

# Get average allocatable resources per worker
get_avg_node_allocatable() {
    local total_cpu=0
    local total_mem=0
    local count=0

    while read -r node; do
        [[ -z "$node" ]] && continue

        local alloc
        alloc=$(oc get node "$node" -o json 2>/dev/null | jq -r '
            .status.allocatable |
            {
                cpu: ((.cpu // "0") | if test("m$") then (.[:-1] | tonumber) else ((. | tonumber) * 1000) end),
                mem: (((.memory // "0") | gsub("Ki$"; "") | tonumber) / 1024)
            }
        ' 2>/dev/null || echo '{"cpu":0,"mem":0}')

        local cpu mem
        cpu=$(echo "$alloc" | jq -r '.cpu // 0' | cut -d'.' -f1)
        mem=$(echo "$alloc" | jq -r '.mem // 0' | cut -d'.' -f1)

        total_cpu=$((total_cpu + cpu))
        total_mem=$((total_mem + mem))
        ((count++))
    done < <(oc get nodes -l 'node-role.kubernetes.io/worker' \
        -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | tr ' ' '\n')

    if [[ $count -gt 0 ]]; then
        echo "$((total_cpu / count)) $((total_mem / count))"
    else
        echo "0 0"
    fi
}

# Get current resource usage (all running pods)
get_current_usage() {
    oc get pods -A -o json 2>/dev/null | jq -r '
        [.items[] | select(.status.phase == "Running") | .spec.containers[].resources.requests // {}] |
        map({
            cpu: ((.cpu // "0") | if test("m$") then (.[:-1] | tonumber) else ((. | tonumber) * 1000) end),
            mem: ((.memory // "0") | if test("Gi$") then ((.[:-2] | tonumber) * 1024) elif test("Mi$") then (.[:-2] | tonumber) elif test("Ki$") then ((.[:-2] | tonumber) / 1024) else 0 end)
        }) |
        {cpu: (map(.cpu) | add // 0), mem: (map(.mem) | add // 0)}
    ' 2>/dev/null || echo '{"cpu":0,"mem":0}'
}

# Count existing HostedClusters (including those being deleted)
get_hostedcluster_count() {
    oc get hostedclusters -n clusters --no-headers 2>/dev/null | wc -l | tr -d ' '
}

# Calculate capacity
current_workers=$(get_current_workers)
max_workers=$(get_max_autoscale_nodes)
read -r avg_cpu avg_mem <<< "$(get_avg_node_allocatable)"

# Total potential capacity (including autoscale headroom)
total_cpu=$((max_workers * avg_cpu))
total_mem=$((max_workers * avg_mem))

# Current usage
usage=$(get_current_usage)
used_cpu=$(echo "$usage" | jq -r '.cpu // 0' | cut -d'.' -f1)
used_mem=$(echo "$usage" | jq -r '.mem // 0' | cut -d'.' -f1)

# Remaining capacity
remaining_cpu=$((total_cpu - used_cpu))
remaining_mem=$((total_mem - used_mem))

# Required with safety margin
required_cpu=$(echo "$CLUSTER_CPU_REQ_M * $SAFETY_MARGIN" | bc | cut -d'.' -f1)
required_mem=$(echo "$CLUSTER_MEM_REQ_MI * $SAFETY_MARGIN" | bc | cut -d'.' -f1)

# Existing clusters
existing_clusters=$(get_hostedcluster_count)

echo "Capacity Analysis:"
echo "  Current workers:     $current_workers"
echo "  Max workers:         $max_workers (with autoscaling)"
echo "  Avg per node:        ${avg_cpu}m CPU, ${avg_mem}Mi MEM"
echo ""
echo "  Total capacity:      ${total_cpu}m CPU, ${total_mem}Mi MEM"
echo "  Current usage:       ${used_cpu}m CPU, ${used_mem}Mi MEM"
echo "  Remaining:           ${remaining_cpu}m CPU, ${remaining_mem}Mi MEM"
echo ""
echo "  Required (+ buffer): ${required_cpu}m CPU, ${required_mem}Mi MEM"
echo "  Existing clusters:   $existing_clusters"
echo ""

# Calculate autoscaler headroom
autoscale_headroom=$((max_workers - current_workers))
headroom_cpu=$((autoscale_headroom * avg_cpu))
headroom_mem=$((autoscale_headroom * avg_mem))

# Check capacity
if [[ $remaining_cpu -ge $required_cpu ]] && [[ $remaining_mem -ge $required_mem ]]; then
    echo "RESULT: Sufficient capacity for new cluster"
    exit 0
elif [[ $autoscale_headroom -gt 0 ]]; then
    # Trust autoscaler: if we can scale up and that would provide enough capacity, proceed
    # New nodes come with ~zero usage, so they provide fresh capacity
    potential_cpu=$((remaining_cpu + headroom_cpu))
    potential_mem=$((remaining_mem + headroom_mem))

    echo "  Autoscale headroom: $autoscale_headroom node(s) can be added"
    echo "  Potential capacity: ${potential_cpu}m CPU, ${potential_mem}Mi MEM"
    echo ""

    if [[ $potential_cpu -ge $required_cpu ]] && [[ $potential_mem -ge $required_mem ]]; then
        echo "RESULT: Trusting autoscaler - capacity available after scale-up"
        echo "  Note: Cluster creation may trigger autoscaler to add nodes"
        exit 0
    else
        echo "RESULT: Insufficient capacity (even with autoscaling)"
        if [[ $potential_cpu -lt $required_cpu ]]; then
            echo "  - Need ${required_cpu}m CPU, only ${potential_cpu}m available (after scale-up)"
        fi
        if [[ $potential_mem -lt $required_mem ]]; then
            echo "  - Need ${required_mem}Mi MEM, only ${potential_mem}Mi available (after scale-up)"
        fi
        exit 1
    fi
else
    echo "RESULT: Insufficient capacity (no autoscaling headroom)"
    if [[ $remaining_cpu -lt $required_cpu ]]; then
        echo "  - Need ${required_cpu}m CPU, only ${remaining_cpu}m available"
    fi
    if [[ $remaining_mem -lt $required_mem ]]; then
        echo "  - Need ${required_mem}Mi MEM, only ${remaining_mem}Mi available"
    fi
    exit 1
fi
