#!/usr/bin/env bash
# shellcheck disable=SC2155
# SC2155: Declare and assign separately - safe here as assignments use fallback defaults
#
# HyperShift Autoscaling Setup
#
# Configures OpenShift autoscaling for cost-optimized bin-packing behavior:
# - Scheduler profile for filling existing nodes before adding new ones
# - ClusterAutoscaler for automatic scale-up/scale-down
# - MachineAutoscalers for per-zone scaling limits
#
# USAGE:
#   # Show current utilization and scaling options (default)
#   ./.github/scripts/hypershift/setup-autoscaling.sh
#
#   # Configure management cluster autoscaling (generates commands for review)
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3
#
#   # Configure with bin-packing scheduler (recommended for cost optimization)
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --scheduler-profile HighNodeUtilization
#
#   # Aggressive cost optimization (faster scale-down, tighter packing)
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --aggressive
#
#   # Apply the generated commands
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --apply
#
# OPTIONS:
#   --nodepool-min N        Minimum nodes for hosted cluster NodePool (default: current replicas)
#   --nodepool-max N        Maximum nodes for hosted cluster NodePool
#   --mgmt-min N            Minimum workers per MachineSet (default: 1)
#   --mgmt-max N            Maximum workers per MachineSet (e.g., 3 means up to 3 per zone)
#   --scheduler-profile P   Set scheduler profile: LowNodeUtilization, HighNodeUtilization, NoScoring
#                           (default: HighNodeUtilization for bin-packing)
#   --aggressive            Use aggressive cost-optimization settings (faster scale-down)
#   --apply                 Actually run the commands (default: dry-run, just print)
#   --help                  Show this help message
#
# SCHEDULER PROFILES:
#   LowNodeUtilization   - Default OpenShift behavior. Spreads pods evenly across nodes.
#                          Good for fault tolerance, but uses more nodes.
#   HighNodeUtilization  - Bin-packing. Fills existing nodes before adding new ones.
#                          Recommended for cost optimization. Fewer nodes, higher utilization.
#   NoScoring            - Fastest scheduling, disables all scoring. Use for very large clusters.
#

set -uo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_cmd() { echo -e "  ${CYAN}\$${NC} $1"; }

# Default values
NODEPOOL_MIN=""
NODEPOOL_MAX=""
MGMT_MIN="1"
MGMT_MAX=""
SCHEDULER_PROFILE="HighNodeUtilization"  # Default to bin-packing for cost optimization
AGGRESSIVE=false
APPLY=false

show_help() {
    cat << 'EOF'
HyperShift Autoscaling Setup

Configures OpenShift autoscaling for cost-optimized bin-packing behavior:
  - Scheduler profile for filling existing nodes before adding new ones
  - ClusterAutoscaler for automatic scale-up/scale-down
  - MachineAutoscalers for per-zone scaling limits

USAGE:
  # Show current utilization and scaling options (default)
  ./.github/scripts/hypershift/setup-autoscaling.sh

  # Configure management cluster autoscaling (generates commands for review)
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3

  # Configure with bin-packing scheduler (recommended for cost optimization)
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --scheduler-profile HighNodeUtilization

  # Aggressive cost optimization (faster scale-down, tighter packing)
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --aggressive

  # Apply the generated commands
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --apply

OPTIONS:
  --nodepool-min N        Minimum nodes for hosted cluster NodePool (default: current replicas)
  --nodepool-max N        Maximum nodes for hosted cluster NodePool
  --mgmt-min N            Minimum workers per MachineSet (default: 1)
  --mgmt-max N            Maximum workers per MachineSet (e.g., 3 means up to 3 per zone)
  --scheduler-profile P   Set scheduler profile (default: HighNodeUtilization)
                          Valid values: LowNodeUtilization, HighNodeUtilization, NoScoring
  --aggressive            Use aggressive cost-optimization settings (faster scale-down)
  --apply                 Actually run the commands (default: dry-run, just print)
  --help, -h              Show this help message

SCHEDULER PROFILES:
  LowNodeUtilization    Default OpenShift behavior. Spreads pods evenly across nodes.
                        Good for fault tolerance, but uses more nodes.

  HighNodeUtilization   Bin-packing. Fills existing nodes before adding new ones.
                        Recommended for cost optimization. Fewer nodes, higher utilization.

  NoScoring             Fastest scheduling, disables all scoring plugins.
                        Use for very large clusters where scheduling latency matters.

EXAMPLES:
  # Preview balanced autoscaling (no changes made)
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4

  # Apply aggressive autoscaling for maximum cost savings
  ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4 --aggressive --apply

  # Configure NodePool autoscaling for hosted clusters
  ./.github/scripts/hypershift/setup-autoscaling.sh --nodepool-max 6 --apply

  # Rollback (remove autoscaling)
  oc delete clusterautoscaler default
  oc delete machineautoscaler -n openshift-machine-api --all

EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --nodepool-min) NODEPOOL_MIN="$2"; shift 2 ;;
        --nodepool-max) NODEPOOL_MAX="$2"; shift 2 ;;
        --mgmt-min) MGMT_MIN="$2"; shift 2 ;;
        --mgmt-max) MGMT_MAX="$2"; shift 2 ;;
        --scheduler-profile) SCHEDULER_PROFILE="$2"; shift 2 ;;
        --aggressive) AGGRESSIVE=true; shift ;;
        --apply) APPLY=true; shift ;;
        --help|-h) show_help ;;
        *) log_error "Unknown option: $1"; show_help ;;
    esac
done

# Validate scheduler profile
case "$SCHEDULER_PROFILE" in
    LowNodeUtilization|HighNodeUtilization|NoScoring) ;;
    *)
        log_error "Invalid scheduler profile: $SCHEDULER_PROFILE"
        log_info "Valid profiles: LowNodeUtilization, HighNodeUtilization, NoScoring"
        exit 1
        ;;
esac

# ============================================================================
# PREREQUISITES
# ============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║           HyperShift Autoscaling Setup                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

log_info "Checking prerequisites..."

if ! command -v oc &>/dev/null; then
    log_error "oc CLI not found"
    exit 1
fi

if ! oc whoami &>/dev/null; then
    log_error "Not logged into OpenShift. Run: oc login <server>"
    exit 1
fi

OC_USER=$(oc whoami 2>/dev/null)
OC_SERVER=$(oc whoami --show-server 2>/dev/null)
log_success "Logged in as: $OC_USER @ $OC_SERVER"
echo ""

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

colorize_pct() {
    local val="$1"
    local num=$(echo "$val" | grep -o '[0-9]*' | head -1 || echo "0")
    if [[ "$num" -ge 90 ]]; then
        echo "${RED}${val}${NC}"
    elif [[ "$num" -ge 70 ]]; then
        echo "${YELLOW}${val}${NC}"
    else
        echo "${GREEN}${val}${NC}"
    fi
}

# ============================================================================
# MANAGEMENT CLUSTER NODE UTILIZATION
# ============================================================================

log_info "Gathering management cluster node utilization..."
echo ""

# Collect node data for sorting
NODE_DATA=""
WORKER_COUNT=0
CONTROL_PLANE_COUNT=0
HIGH_UTIL_WORKERS=0

while IFS= read -r name; do
    [[ -z "$name" ]] && continue

    # Get node details in one call
    node_json=$(oc get node "$name" -o json 2>/dev/null)

    # Role
    roles=$(echo "$node_json" | jq -r '.metadata.labels | keys[]' 2>/dev/null | grep 'node-role.kubernetes.io' | sed 's/node-role.kubernetes.io\///' || echo "")
    if [[ "$roles" == *"master"* ]] || [[ "$roles" == *"control-plane"* ]]; then
        role="control-plane"
        role_sort="0"  # Sort control-plane first
        ((CONTROL_PLANE_COUNT++)) || true
    else
        role="worker"
        role_sort="1"
        ((WORKER_COUNT++)) || true
    fi

    # Zone (last char of zone label, e.g., us-east-1a -> 1a)
    zone_full=$(echo "$node_json" | jq -r '.metadata.labels["topology.kubernetes.io/zone"] // "unknown"' 2>/dev/null)
    zone=$(echo "$zone_full" | grep -o '[0-9][a-z]$' || echo "$zone_full")

    # Instance ID (from provider ID: aws:///us-east-1a/i-0abc123...)
    provider_id=$(echo "$node_json" | jq -r '.spec.providerID // ""' 2>/dev/null)
    instance_id=$(echo "$provider_id" | grep -o 'i-[a-z0-9]*' || echo "-")

    # Instance type
    instance_type=$(echo "$node_json" | jq -r '.metadata.labels["node.kubernetes.io/instance-type"] // "unknown"' 2>/dev/null)

    # Creation date
    created_full=$(echo "$node_json" | jq -r '.metadata.creationTimestamp // ""' 2>/dev/null)
    created=$(echo "$created_full" | cut -d'T' -f1)  # Just the date part

    # Get resource allocation
    alloc=$(oc describe node "$name" 2>/dev/null | grep -A 6 "Allocated resources" || echo "")

    cpu_pcts=$(echo "$alloc" | grep "cpu" | grep -o '([0-9]*%)' | tr -d '()' || echo "")
    cpu_req=$(echo "$cpu_pcts" | head -1)
    cpu_lim=$(echo "$cpu_pcts" | tail -1)
    [[ -z "$cpu_req" ]] && cpu_req="N/A"
    [[ -z "$cpu_lim" ]] && cpu_lim="N/A"

    mem_pcts=$(echo "$alloc" | grep "memory" | grep -o '([0-9]*%)' | tr -d '()' || echo "")
    mem_req=$(echo "$mem_pcts" | head -1)
    mem_lim=$(echo "$mem_pcts" | tail -1)
    [[ -z "$mem_req" ]] && mem_req="N/A"
    [[ -z "$mem_lim" ]] && mem_lim="N/A"

    # Check high utilization
    cpu_num=$(echo "$cpu_req" | grep -o '[0-9]*' | head -1 || echo "0")
    if [[ "$cpu_num" -ge 80 ]] && [[ "$role" == "worker" ]]; then
        ((HIGH_UTIL_WORKERS++)) || true
    fi

    # Collect data for sorting: role_sort|created|zone|instance_id|role|instance_type|cpu_req|cpu_lim|mem_req|mem_lim
    NODE_DATA+="${role_sort}|${created}|${zone}|${instance_id}|${role}|${instance_type}|${cpu_req}|${cpu_lim}|${mem_req}|${mem_lim}\n"

done < <(oc get nodes -o custom-columns='NAME:.metadata.name' --no-headers 2>/dev/null)

# Print node table
echo -e "${BOLD}Management Cluster Nodes:${NC}"
echo ""
echo "  Rq = Requests (scheduling), Lm = Limits (throttling)"
echo ""
printf "  %-12s %-4s %-21s %-11s %-12s %-7s %-7s %-7s %-7s\n" "ROLE" "ZONE" "INSTANCE ID" "TYPE" "CREATED" "CPU Rq" "CPU Lm" "MEM Rq" "MEM Lm"
printf "  %-12s %-4s %-21s %-11s %-12s %-7s %-7s %-7s %-7s\n" "------------" "----" "---------------------" "-----------" "------------" "-------" "-------" "-------" "-------"

# Sort: by role (control-plane first), then by creation date
SORTED_DATA=$(echo -e "$NODE_DATA" | sort -t'|' -k1,1 -k2,2)

while IFS='|' read -r role_sort created zone instance_id role instance_type cpu_req cpu_lim mem_req mem_lim; do
    [[ -z "$role" ]] && continue

    cpu_req_c=$(colorize_pct "$cpu_req")
    cpu_lim_c=$(colorize_pct "$cpu_lim")
    mem_req_c=$(colorize_pct "$mem_req")
    mem_lim_c=$(colorize_pct "$mem_lim")

    printf "  %-12s %-4s %-21s %-11s %-12s %-18b %-18b %-18b %-18b\n" "$role" "$zone" "$instance_id" "$instance_type" "$created" "$cpu_req_c" "$cpu_lim_c" "$mem_req_c" "$mem_lim_c"
done <<< "$SORTED_DATA"

echo ""
if [[ $HIGH_UTIL_WORKERS -gt 0 ]]; then
    log_warn "$HIGH_UTIL_WORKERS worker(s) at 80%+ CPU requests - scaling recommended"
fi
echo ""

# ============================================================================
# MACHINESETS (Management Cluster Scaling)
# ============================================================================

log_info "Checking MachineSets for management cluster scaling..."
echo ""

# Try to get machinesets
MACHINESETS_OUTPUT=$(oc get machinesets.machine.openshift.io -n openshift-machine-api -o wide 2>/dev/null || echo "")

if [[ -z "$MACHINESETS_OUTPUT" ]]; then
    log_warn "Cannot access MachineSets - need cluster-admin or Machine API access"
    MGMT_HAS_MACHINESETS=false
else
    MGMT_HAS_MACHINESETS=true
    echo -e "${BOLD}MachineSets (for scaling management cluster workers):${NC}"
    echo ""
    echo "$MACHINESETS_OUTPUT" | while IFS= read -r line; do echo "  $line"; done
    echo ""

    # Parse active machinesets (those with replicas > 0 or that we can scale)
    declare -a ACTIVE_MACHINESETS=()
    while IFS= read -r ms; do
        [[ -z "$ms" ]] && continue
        ACTIVE_MACHINESETS+=("$ms")
    done < <(oc get machinesets.machine.openshift.io -n openshift-machine-api -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
fi

# Check current autoscaling config
log_info "Checking current autoscaling configuration..."
echo ""

CLUSTER_AUTOSCALER=$(oc get clusterautoscaler default -o name 2>/dev/null || echo "")
if [[ -n "$CLUSTER_AUTOSCALER" ]]; then
    log_success "ClusterAutoscaler: configured"
    oc get clusterautoscaler default -o jsonpath='  maxNodesTotal: {.spec.resourceLimits.maxNodesTotal}{"\n"}' 2>/dev/null || true
else
    log_warn "ClusterAutoscaler: not configured"
fi

MACHINE_AUTOSCALERS=$(oc get machineautoscaler -n openshift-machine-api --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$MACHINE_AUTOSCALERS" -gt 0 ]]; then
    log_success "MachineAutoscalers: $MACHINE_AUTOSCALERS configured"
    oc get machineautoscaler -n openshift-machine-api 2>/dev/null | while IFS= read -r line; do echo "  $line"; done
else
    log_warn "MachineAutoscalers: none configured"
fi

echo ""

# ============================================================================
# HOSTED CLUSTER / NODEPOOL INFO
# ============================================================================

log_info "Checking HyperShift hosted clusters..."
echo ""

NODEPOOL_NAME=""
NODEPOOL_NS=""
NODEPOOL_CURRENT_REPLICAS="2"

# Get hosted clusters
HOSTED_CLUSTERS=$(oc get hostedclusters -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

if [[ -z "$HOSTED_CLUSTERS" ]]; then
    log_warn "No hosted clusters found"
    CLUSTER_COUNT=0
else
    # Get all nodepools directly (avoid duplicates)
    NODEPOOLS=$(oc get nodepools -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")

    if [[ -n "$NODEPOOLS" ]]; then
        echo -e "${BOLD}NodePools:${NC}"
        echo ""
        printf "  %-38s %-10s %-10s %-12s %-10s\n" "NODEPOOL" "DESIRED" "CURRENT" "AUTOSCALING" "MIN/MAX"
        printf "  %-38s %-10s %-10s %-12s %-10s\n" "--------------------------------------" "----------" "----------" "------------" "----------"

        while IFS= read -r np_entry; do
            [[ -z "$np_entry" ]] && continue
            ns=$(echo "$np_entry" | cut -d'/' -f1)
            np_name=$(echo "$np_entry" | cut -d'/' -f2)

            np_desired=$(oc get nodepool "$np_name" -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "-")
            np_current=$(oc get nodepool "$np_name" -n "$ns" -o jsonpath='{.status.replicas}' 2>/dev/null || echo "-")
            np_min=$(oc get nodepool "$np_name" -n "$ns" -o jsonpath='{.spec.autoScaling.min}' 2>/dev/null || echo "")
            np_max=$(oc get nodepool "$np_name" -n "$ns" -o jsonpath='{.spec.autoScaling.max}' 2>/dev/null || echo "")

            if [[ -n "$np_min" ]] && [[ -n "$np_max" ]]; then
                autoscale_status="${GREEN}Enabled${NC}"
                autoscale_info="${np_min}/${np_max}"
            else
                autoscale_status="${YELLOW}Disabled${NC}"
                autoscale_info="-"
            fi

            [[ "$np_desired" == "" ]] && np_desired="-"
            [[ "$np_current" == "" ]] && np_current="-"

            printf "  %-38s %-10s %-10s %-23b %-10s\n" "$np_name" "$np_desired" "$np_current" "$autoscale_status" "$autoscale_info"

            NODEPOOL_NAME="$np_name"
            NODEPOOL_NS="$ns"
            [[ "$np_desired" != "-" ]] && NODEPOOL_CURRENT_REPLICAS="$np_desired"
        done <<< "$NODEPOOLS"
        echo ""
    fi

    # =========================================================================
    # HOSTED CLUSTER RESOURCE USAGE
    # =========================================================================

    echo -e "${BOLD}Hosted Cluster Control Plane Resources:${NC}"
    echo ""
    printf "  %-30s %-10s %-12s %-12s %-10s\n" "CLUSTER" "STATUS" "CPU Req" "MEM Req" "PODS"
    printf "  %-30s %-10s %-12s %-12s %-10s\n" "------------------------------" "----------" "------------" "------------" "----------"

    CLUSTER_COUNT=0
    READY_CLUSTER_COUNT=0
    TOTAL_CLUSTER_CPU_REQ=0
    TOTAL_CLUSTER_MEM_REQ=0

    while IFS= read -r hc_entry; do
        [[ -z "$hc_entry" ]] && continue
        hc_ns=$(echo "$hc_entry" | cut -d'/' -f1)
        hc_name=$(echo "$hc_entry" | cut -d'/' -f2)

        # Get cluster status
        hc_available=$(oc get hostedcluster "$hc_name" -n "$hc_ns" -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "Unknown")
        if [[ "$hc_available" == "True" ]]; then
            status="${GREEN}Ready${NC}"
            is_ready=true
        else
            status="${YELLOW}NotReady${NC}"
            is_ready=false
        fi

        # Control plane namespace is typically clusters-<name>
        cp_ns="clusters-${hc_name}"

        # Sum CPU and memory requests for all pods in the control plane namespace
        # CPU is in millicores (e.g., 100m, 1, 2000m)
        # Memory is in bytes (e.g., 128Mi, 1Gi)
        pod_resources=$(oc get pods -n "$cp_ns" -o json 2>/dev/null | jq -r '
            [.items[].spec.containers[].resources.requests // {}] |
            map({
                cpu: ((.cpu // "0") | if test("m$") then (.[:-1] | tonumber) else ((. | tonumber) * 1000) end),
                mem: ((.memory // "0") | if test("Gi$") then ((.[:-2] | tonumber) * 1024) elif test("Mi$") then (.[:-2] | tonumber) elif test("Ki$") then ((.[:-2] | tonumber) / 1024) else 0 end)
            }) |
            {cpu: (map(.cpu) | add), mem: (map(.mem) | add)}
        ' 2>/dev/null || echo '{"cpu":0,"mem":0}')

        cpu_req_m=$(echo "$pod_resources" | jq -r '.cpu // 0' | cut -d'.' -f1)
        mem_req_mi=$(echo "$pod_resources" | jq -r '.mem // 0' | cut -d'.' -f1)

        # Count pods
        pod_count=$(oc get pods -n "$cp_ns" --no-headers 2>/dev/null | wc -l | tr -d ' ')

        # Format for display
        if [[ "$cpu_req_m" -ge 1000 ]]; then
            cpu_display="$(echo "scale=1; $cpu_req_m / 1000" | bc)c"
        else
            cpu_display="${cpu_req_m}m"
        fi

        if [[ "$mem_req_mi" -ge 1024 ]]; then
            mem_display="$(echo "scale=1; $mem_req_mi / 1024" | bc)Gi"
        else
            mem_display="${mem_req_mi}Mi"
        fi

        printf "  %-30s %-21b %-12s %-12s %-10s\n" "$hc_name" "$status" "$cpu_display" "$mem_display" "$pod_count"

        ((CLUSTER_COUNT++)) || true
        # Only count Ready clusters for average calculation
        if [[ "$is_ready" == "true" ]]; then
            ((READY_CLUSTER_COUNT++)) || true
            TOTAL_CLUSTER_CPU_REQ=$((TOTAL_CLUSTER_CPU_REQ + cpu_req_m))
            TOTAL_CLUSTER_MEM_REQ=$((TOTAL_CLUSTER_MEM_REQ + mem_req_mi))
        fi

    done <<< "$HOSTED_CLUSTERS"

    echo ""

    # =========================================================================
    # CAPACITY CALCULATION
    # =========================================================================

    if [[ $CLUSTER_COUNT -gt 0 ]]; then
        # Get total allocatable resources from worker nodes
        TOTAL_ALLOC_CPU=0
        TOTAL_ALLOC_MEM=0

        while IFS= read -r node_line; do
            [[ -z "$node_line" ]] && continue
            # Skip master nodes (only process workers)
            is_master=$(oc get node "$node_line" -o jsonpath='{.metadata.labels.node-role\.kubernetes\.io/master}' 2>/dev/null)
            [[ -n "$is_master" ]] && continue

            alloc=$(oc get node "$node_line" -o json 2>/dev/null | jq -r '
                .status.allocatable |
                {
                    cpu: ((.cpu // "0") | if test("m$") then (.[:-1] | tonumber) else ((. | tonumber) * 1000) end),
                    mem: (((.memory // "0") | gsub("Ki$"; "") | tonumber) / 1024)
                }
            ' 2>/dev/null || echo '{"cpu":0,"mem":0}')

            node_cpu=$(echo "$alloc" | jq -r '.cpu' | cut -d'.' -f1)
            node_mem=$(echo "$alloc" | jq -r '.mem' | cut -d'.' -f1)

            TOTAL_ALLOC_CPU=$((TOTAL_ALLOC_CPU + node_cpu))
            TOTAL_ALLOC_MEM=$((TOTAL_ALLOC_MEM + node_mem))
        done < <(oc get nodes -o custom-columns='NAME:.metadata.name' --no-headers 2>/dev/null)

        # Get total current requests from all pods on workers
        TOTAL_USED_CPU=0
        TOTAL_USED_MEM=0

        all_pod_resources=$(oc get pods -A -o json 2>/dev/null | jq -r '
            [.items[] | select(.status.phase == "Running") | .spec.containers[].resources.requests // {}] |
            map({
                cpu: ((.cpu // "0") | if test("m$") then (.[:-1] | tonumber) else ((. | tonumber) * 1000) end),
                mem: ((.memory // "0") | if test("Gi$") then ((.[:-2] | tonumber) * 1024) elif test("Mi$") then (.[:-2] | tonumber) elif test("Ki$") then ((.[:-2] | tonumber) / 1024) else 0 end)
            }) |
            {cpu: (map(.cpu) | add), mem: (map(.mem) | add)}
        ' 2>/dev/null || echo '{"cpu":0,"mem":0}')

        TOTAL_USED_CPU=$(echo "$all_pod_resources" | jq -r '.cpu // 0' | cut -d'.' -f1)
        TOTAL_USED_MEM=$(echo "$all_pod_resources" | jq -r '.mem // 0' | cut -d'.' -f1)

        # Calculate remaining capacity
        REMAINING_CPU=$((TOTAL_ALLOC_CPU - TOTAL_USED_CPU))
        REMAINING_MEM=$((TOTAL_ALLOC_MEM - TOTAL_USED_MEM))

        # Average cluster footprint (only from Ready clusters)
        if [[ $READY_CLUSTER_COUNT -gt 0 ]]; then
            AVG_CLUSTER_CPU=$((TOTAL_CLUSTER_CPU_REQ / READY_CLUSTER_COUNT))
            AVG_CLUSTER_MEM=$((TOTAL_CLUSTER_MEM_REQ / READY_CLUSTER_COUNT))
        else
            AVG_CLUSTER_CPU=0
            AVG_CLUSTER_MEM=0
        fi

        # How many more clusters can fit?
        if [[ $AVG_CLUSTER_CPU -gt 0 ]] && [[ $AVG_CLUSTER_MEM -gt 0 ]]; then
            FIT_BY_CPU=$((REMAINING_CPU / AVG_CLUSTER_CPU))
            FIT_BY_MEM=$((REMAINING_MEM / AVG_CLUSTER_MEM))
            # Take the minimum
            if [[ $FIT_BY_CPU -lt $FIT_BY_MEM ]]; then
                CAN_FIT=$FIT_BY_CPU
                LIMITING="CPU"
            else
                CAN_FIT=$FIT_BY_MEM
                LIMITING="memory"
            fi
        else
            CAN_FIT=0
            LIMITING="unknown"
        fi

        # Format numbers for display
        fmt_cpu() {
            local m=$1
            if [[ $m -ge 1000 ]]; then
                echo "$(echo "scale=1; $m / 1000" | bc) cores"
            else
                echo "${m}m"
            fi
        }

        fmt_mem() {
            local mi=$1
            if [[ $mi -ge 1024 ]]; then
                echo "$(echo "scale=1; $mi / 1024" | bc) Gi"
            else
                echo "${mi} Mi"
            fi
        }

        echo -e "${BOLD}Capacity Summary:${NC}"
        echo ""
        echo "  Worker nodes:        ${WORKER_COUNT}"
        echo "  Allocatable:         $(fmt_cpu $TOTAL_ALLOC_CPU), $(fmt_mem $TOTAL_ALLOC_MEM)"
        echo "  Current requests:    $(fmt_cpu $TOTAL_USED_CPU), $(fmt_mem $TOTAL_USED_MEM)"
        echo "  Remaining:           $(fmt_cpu $REMAINING_CPU), $(fmt_mem $REMAINING_MEM)"
        echo ""
        echo "  Hosted clusters:     ${CLUSTER_COUNT} total, ${READY_CLUSTER_COUNT} ready"
        echo "  Avg cluster size:    $(fmt_cpu $AVG_CLUSTER_CPU), $(fmt_mem $AVG_CLUSTER_MEM) (based on ${READY_CLUSTER_COUNT} ready)"
        echo ""
        if [[ $READY_CLUSTER_COUNT -eq 0 ]]; then
            echo -e "  ${YELLOW}No ready clusters to calculate capacity estimate${NC}"
        elif [[ $CAN_FIT -gt 0 ]]; then
            echo -e "  ${GREEN}Can fit ~${CAN_FIT} more cluster(s)${NC} (limited by ${LIMITING})"
        else
            echo -e "  ${RED}At capacity${NC} - no room for additional clusters without scaling"
        fi
        echo ""
    fi
fi

# ============================================================================
# GENERATE COMMANDS
# ============================================================================

if [[ -n "$MGMT_MAX" ]] || [[ -n "$NODEPOOL_MAX" ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ "$APPLY" == "true" ]]; then
        echo -e " ${GREEN}APPLYING${NC} — executing commands now"
    else
        echo -e " ${YELLOW}DRY RUN${NC} — review commands, then re-run with --apply"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Management cluster autoscaling
    if [[ -n "$MGMT_MAX" ]]; then
        if [[ "$MGMT_HAS_MACHINESETS" != "true" ]]; then
            log_error "Cannot configure management autoscaling - no MachineSet access"
            log_info "Run with cluster-admin: oc get machinesets -n openshift-machine-api"
        else
            # Get list of ACTIVE worker machinesets (DESIRED > 0 or CURRENT > 0)
            WORKER_MS=$(oc get machinesets.machine.openshift.io -n openshift-machine-api -o jsonpath='{range .items[?(@.spec.replicas>0)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -v master || echo "")
            if [[ -z "$WORKER_MS" ]]; then
                WORKER_MS=$(oc get machinesets.machine.openshift.io -n openshift-machine-api -o jsonpath='{range .items[?(@.status.replicas>0)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -v master || echo "")
            fi
            MS_COUNT=$(echo "$WORKER_MS" | grep -c . || echo "0")
            MAX_TOTAL=$((CONTROL_PLANE_COUNT + (MS_COUNT * MGMT_MAX)))

            echo " Config: ${MS_COUNT} active zones × min=${MGMT_MIN}/max=${MGMT_MAX} = up to $((MS_COUNT * MGMT_MAX)) workers"
            echo " Scheduler profile: ${SCHEDULER_PROFILE}"
            [[ "$AGGRESSIVE" == "true" ]] && echo -e " Mode: ${YELLOW}AGGRESSIVE${NC} (faster scale-down)"
            echo ""

            # Set timing values based on mode
            if [[ "$AGGRESSIVE" == "true" ]]; then
                # Aggressive: faster scale-down for cost optimization
                DELAY_AFTER_ADD="3m"
                DELAY_AFTER_DELETE="1m"
                DELAY_AFTER_FAILURE="1m"
                UNNEEDED_TIME="3m"
                UTILIZATION_THRESHOLD="0.5"
            else
                # Balanced: reasonable defaults for production
                DELAY_AFTER_ADD="5m"
                DELAY_AFTER_DELETE="3m"
                DELAY_AFTER_FAILURE="3m"
                UNNEEDED_TIME="5m"
                UTILIZATION_THRESHOLD="0.5"
            fi

            # ================================================================
            # Step 1: Configure Scheduler Profile
            # ================================================================
            echo "  # Step 1: Configure Scheduler Profile (${SCHEDULER_PROFILE})"
            echo ""
            SCHED_CMD="oc patch scheduler cluster --type=merge -p '{\"spec\":{\"profile\":\"${SCHEDULER_PROFILE}\"}}'"
            log_cmd "$SCHED_CMD"
            echo ""
            echo "  # Scheduler Profiles:"
            echo "  #   LowNodeUtilization  - Spreads pods across nodes (default, more nodes)"
            echo "  #   HighNodeUtilization - Bin-packing, fills nodes first (fewer nodes, cost-optimized)"
            echo "  #   NoScoring           - Fastest scheduling, no scoring (large clusters only)"
            echo ""

            if [[ "$APPLY" == "true" ]]; then
                eval "$SCHED_CMD"
                log_success "Scheduler profile set to ${SCHEDULER_PROFILE}"
                echo ""
            fi

            # ================================================================
            # Step 2: Create ClusterAutoscaler
            # ================================================================
            echo "  # Step 2: Create ClusterAutoscaler"
            echo ""
            CA_CMD="oc apply -f - <<'EOF'
apiVersion: autoscaling.openshift.io/v1
kind: ClusterAutoscaler
metadata:
  name: default
spec:
  # ============================================================================
  # SCALING BEHAVIOR
  # ============================================================================

  # balanceSimilarNodeGroups: Controls whether to keep similar node groups
  # (same instance type, same labels) balanced in size.
  #   true  = Balance nodes across zones (default). Good for HA, but prevents
  #           scale-down if one zone has more nodes than others.
  #   false = Allow unbalanced zones. Enables more aggressive scale-down but
  #           may concentrate workloads in fewer zones.
  # For cost optimization with multi-AZ, set to false to allow scale-down.
  balanceSimilarNodeGroups: false

  # podPriorityThreshold: Pods with priority below this value will NOT trigger
  # scale-up. Use negative values (-10) to prevent low-priority batch jobs
  # from adding nodes. Set to 0 to scale up for all pods.
  # Range: any integer, typically -10 to 0
  podPriorityThreshold: -10

  # ignoreDaemonsetsUtilization: If true, DaemonSet pods are not counted when

  # calculating node utilization for scale-down decisions.
  #   true  = Nodes with only DaemonSets can scale down (cost-optimized)
  #   false = DaemonSets count toward utilization (more conservative)
  ignoreDaemonsetsUtilization: true

  # skipNodesWithLocalStorage: If true, nodes with pods using local storage
  # (emptyDir, hostPath) will NOT be considered for scale-down.
  #   true  = Protect nodes with local storage (safer for stateful apps)
  #   false = Allow scale-down even with local storage (more aggressive)
  skipNodesWithLocalStorage: true

  # ============================================================================
  # RESOURCE LIMITS
  # ============================================================================
  resourceLimits:
    # maxNodesTotal: Maximum number of nodes (workers + control plane) the
    # autoscaler will provision. Set this to prevent runaway scaling.
    maxNodesTotal: ${MAX_TOTAL}

    # Optional: Set min/max cores and memory across the cluster
    # cores:
    #   min: 8
    #   max: 128
    # memory:
    #   min: 16    # in GB
    #   max: 512   # in GB

  # ============================================================================
  # SCALE-DOWN CONFIGURATION
  # ============================================================================
  scaleDown:
    # enabled: Master switch for scale-down. Set to false to only allow scale-up.
    enabled: true

    # delayAfterAdd: Time to wait after a node is added before considering
    # ANY node for scale-down. Allows new nodes to stabilize.
    # Aggressive: 3m, Balanced: 5m, Conservative: 10m
    delayAfterAdd: ${DELAY_AFTER_ADD}

    # delayAfterDelete: Time to wait after a node is deleted before considering
    # another scale-down. Prevents rapid cascading deletions.
    # Aggressive: 1m, Balanced: 3m, Conservative: 5m
    delayAfterDelete: ${DELAY_AFTER_DELETE}

    # delayAfterFailure: Time to wait after a failed scale-down attempt before
    # retrying. Handles transient failures.
    # Aggressive: 1m, Balanced: 3m, Conservative: 5m
    delayAfterFailure: ${DELAY_AFTER_FAILURE}

    # unneededTime: Duration a node must be underutilized before it becomes
    # eligible for scale-down. Lower = faster response, but may cause flapping.
    # Aggressive: 3m, Balanced: 5m, Conservative: 10m
    unneededTime: ${UNNEEDED_TIME}

    # utilizationThreshold: Node utilization (CPU/memory) below which a node
    # is considered underutilized and eligible for scale-down.
    # Value is a decimal string: "0.5" = 50% utilization threshold
    # Lower values = more aggressive scale-down (e.g., "0.3" = 30%)
    # Higher values = keep nodes longer (e.g., "0.7" = 70%)
    utilizationThreshold: "${UTILIZATION_THRESHOLD}"
EOF"
            log_cmd "$CA_CMD"
            echo ""

            if [[ "$APPLY" == "true" ]]; then
                eval "$CA_CMD"
                log_success "ClusterAutoscaler created/updated"
                echo ""
            fi

            # ================================================================
            # Step 3: Create MachineAutoscaler for each worker MachineSet
            # ================================================================
            echo "  # Step 3: Create MachineAutoscaler for each worker MachineSet"
            echo ""
            echo "  # MachineAutoscaler defines min/max replicas per MachineSet (per zone)"
            echo "  # The ClusterAutoscaler uses these to determine scaling boundaries."
            echo ""

            while IFS= read -r ms_name; do
                [[ -z "$ms_name" ]] && continue

                MA_CMD="oc apply -f - <<EOF
apiVersion: autoscaling.openshift.io/v1beta1
kind: MachineAutoscaler
metadata:
  name: ${ms_name}-autoscaler
  namespace: openshift-machine-api
spec:
  # minReplicas: Minimum number of nodes to maintain in this MachineSet.
  # WARNING: Do NOT set to 0 for default worker MachineSets created during
  # cluster installation. Use 1 as minimum for production clusters.
  minReplicas: ${MGMT_MIN}

  # maxReplicas: Maximum number of nodes the autoscaler can provision.
  # This is per-MachineSet (per-zone), not cluster-wide.
  maxReplicas: ${MGMT_MAX}

  # scaleTargetRef: Reference to the MachineSet to autoscale
  scaleTargetRef:
    apiVersion: machine.openshift.io/v1beta1
    kind: MachineSet
    name: ${ms_name}
EOF"
                log_cmd "$MA_CMD"
                echo ""

                if [[ "$APPLY" == "true" ]]; then
                    eval "$MA_CMD"
                    log_success "MachineAutoscaler ${ms_name}-autoscaler created/updated"
                    echo ""
                fi
            done <<< "$WORKER_MS"
        fi
    fi

    # NodePool autoscaling
    if [[ -n "$NODEPOOL_MAX" ]]; then
        echo -e "${BOLD}NodePool Autoscaling Commands:${NC}"
        echo ""

        if [[ -z "$NODEPOOL_NAME" ]]; then
            log_warn "No NodePool found to configure"
        else
            NP_MIN="${NODEPOOL_MIN:-${NODEPOOL_CURRENT_REPLICAS}}"

            NP_CMD="oc patch nodepool/${NODEPOOL_NAME} -n ${NODEPOOL_NS} --type=merge -p '{
  \"spec\": {
    \"replicas\": null,
    \"autoScaling\": {
      \"min\": ${NP_MIN},
      \"max\": ${NODEPOOL_MAX}
    }
  }
}'"
            log_cmd "$NP_CMD"
            echo ""

            if [[ "$APPLY" == "true" ]]; then
                eval "$NP_CMD"
                log_success "NodePool ${NODEPOOL_NAME} autoscaling configured"
                echo ""
            fi
        fi
    fi

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ "$APPLY" != "true" ]]; then
        echo ""
        echo " To apply, run:"
        cmd="./.github/scripts/hypershift/setup-autoscaling.sh"
        [[ -n "$MGMT_MAX" ]] && cmd="$cmd --mgmt-min $MGMT_MIN --mgmt-max $MGMT_MAX"
        [[ -n "$NODEPOOL_MAX" ]] && cmd="$cmd --nodepool-max $NODEPOOL_MAX"
        cmd="$cmd --apply"
        echo ""
        echo "    $cmd"
        echo ""
    else
        echo ""
        log_success "Done! Showing current status:"
        echo ""

        # Show scheduler profile
        echo -e "${BOLD}Scheduler Profile:${NC}"
        CURRENT_PROFILE=$(oc get scheduler cluster -o jsonpath='{.spec.profile}' 2>/dev/null || echo "not set")
        echo "  Current profile: ${CURRENT_PROFILE}"
        echo ""

        # Show ClusterAutoscaler
        echo -e "${BOLD}ClusterAutoscaler:${NC}"
        if oc get clusterautoscaler default &>/dev/null; then
            oc get clusterautoscaler default -o custom-columns='NAME:.metadata.name,MAX_NODES:.spec.resourceLimits.maxNodesTotal,SCALE_DOWN:.spec.scaleDown.enabled,UNNEEDED_TIME:.spec.scaleDown.unneededTime,UTIL_THRESHOLD:.spec.scaleDown.utilizationThreshold' 2>/dev/null | while IFS= read -r line; do echo "  $line"; done
        else
            echo "  (not found)"
        fi
        echo ""

        # Show MachineAutoscalers
        echo -e "${BOLD}MachineAutoscalers:${NC}"
        MA_COUNT=$(oc get machineautoscaler -n openshift-machine-api --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$MA_COUNT" -gt 0 ]]; then
            oc get machineautoscaler -n openshift-machine-api -o custom-columns='NAME:.metadata.name,MIN:.spec.minReplicas,MAX:.spec.maxReplicas,TARGET:.spec.scaleTargetRef.name' 2>/dev/null | while IFS= read -r line; do echo "  $line"; done
        else
            echo "  (none configured)"
        fi
        echo ""

        # Show NodePool autoscaling if configured
        if [[ -n "$NODEPOOL_NAME" ]]; then
            echo -e "${BOLD}NodePool Autoscaling:${NC}"
            oc get nodepool "$NODEPOOL_NAME" -n "$NODEPOOL_NS" -o custom-columns='NAME:.metadata.name,MIN:.spec.autoScaling.min,MAX:.spec.autoScaling.max,CURRENT:.status.replicas' 2>/dev/null | while IFS= read -r line; do echo "  $line"; done
            echo ""
        fi

        # Show current node count
        echo -e "${BOLD}Current Nodes:${NC}"
        WORKER_COUNT=$(oc get nodes --selector='!node-role.kubernetes.io/master' --no-headers 2>/dev/null | wc -l | tr -d ' ')
        MASTER_COUNT=$(oc get nodes --selector='node-role.kubernetes.io/master' --no-headers 2>/dev/null | wc -l | tr -d ' ')
        echo "  Control plane: ${MASTER_COUNT}"
        echo "  Workers: ${WORKER_COUNT}"
        echo "  Total: $((MASTER_COUNT + WORKER_COUNT))"
        echo ""
    fi

else
    # =========================================================================
    # NO OPTIONS - SHOW SCALING OPTIONS
    # =========================================================================

    if [[ "$MGMT_HAS_MACHINESETS" == "true" ]]; then
        # Collect active and inactive machinesets
        declare -a ACTIVE_MS_NAMES=()
        declare -a ACTIVE_MS_REPLICAS=()
        declare -a INACTIVE_MS_NAMES=()

        while IFS= read -r ms_line; do
            [[ -z "$ms_line" ]] && continue
            ms_name=$(echo "$ms_line" | awk '{print $1}')
            ms_current=$(echo "$ms_line" | awk '{print $2}')
            [[ "$ms_name" == "NAME" ]] && continue

            if [[ "$ms_current" == "0" ]]; then
                INACTIVE_MS_NAMES+=("$ms_name")
            else
                ACTIVE_MS_NAMES+=("$ms_name")
                ACTIVE_MS_REPLICAS+=("$ms_current")
            fi
        done < <(oc get machinesets.machine.openshift.io -n openshift-machine-api --no-headers 2>/dev/null | grep -v master)

        # Summary line
        ACTIVE_SUMMARY=""
        for i in "${!ACTIVE_MS_NAMES[@]}"; do
            short=$(echo "${ACTIVE_MS_NAMES[$i]}" | sed 's/base-rdmbg-worker-//')
            ACTIVE_SUMMARY="${ACTIVE_SUMMARY}${short}(${ACTIVE_MS_REPLICAS[$i]}) "
        done

        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "${BOLD} SCALING OPTIONS${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo -e " Active zones:   ${GREEN}${ACTIVE_SUMMARY}${NC}"
        if [[ ${#INACTIVE_MS_NAMES[@]} -gt 0 ]]; then
            INACTIVE_SUMMARY=""
            for ms in "${INACTIVE_MS_NAMES[@]}"; do
                short=$(echo "$ms" | sed 's/base-rdmbg-worker-//')
                INACTIVE_SUMMARY="${INACTIVE_SUMMARY}${short} "
            done
            echo -e " Inactive zones: ${YELLOW}${INACTIVE_SUMMARY}${NC}(0 replicas, skipped)"
        fi
        echo ""

        # Option 1: Manual scaling
        echo -e "${BOLD}[1] MANUAL SCALING${NC} — add workers immediately"
        echo ""
        for i in "${!ACTIVE_MS_NAMES[@]}"; do
            echo "    oc scale machineset.machine.openshift.io/${ACTIVE_MS_NAMES[$i]} -n openshift-machine-api --replicas=2"
        done
        echo ""

        # Option 2: Autoscaling (balanced)
        echo -e "${BOLD}[2] ENABLE AUTOSCALING (BALANCED)${NC} — automatic scaling with bin-packing"
        echo ""
        echo "    # Preview (uses HighNodeUtilization scheduler for bin-packing):"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4"
        echo ""
        echo "    # Apply:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4 --apply"
        echo ""

        # Option 3: Autoscaling (aggressive)
        echo -e "${BOLD}[3] ENABLE AUTOSCALING (AGGRESSIVE)${NC} — faster scale-down, cost-optimized"
        echo ""
        echo "    # Preview with aggressive settings (faster scale-down timers):"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4 --aggressive"
        echo ""
        echo "    # Apply:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 4 --aggressive --apply"
        echo ""

        # Rollback
        echo -e "${BOLD}[4] ROLLBACK AUTOSCALING${NC} — remove autoscaler config"
        echo ""
        echo "    oc delete clusterautoscaler default"
        echo "    oc delete machineautoscaler -n openshift-machine-api --all"
        echo ""

    else
        echo ""
        echo "  Management cluster scaling requires cluster-admin access."
        echo "  Run: oc login with cluster-admin credentials"
        echo ""
    fi

    if [[ -n "$NODEPOOL_NAME" ]]; then
        echo -e "${BOLD}[5] NODEPOOL AUTOSCALING${NC} — scale hosted cluster workers"
        echo ""
        echo "    # Preview:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --nodepool-max 6"
        echo ""
        echo "    # Apply:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --nodepool-max 6 --apply"
        echo ""
    fi

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi
