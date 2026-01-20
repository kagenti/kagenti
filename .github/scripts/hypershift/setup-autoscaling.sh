#!/usr/bin/env bash
#
# HyperShift Autoscaling Setup
#
# Shows cluster utilization and helps configure autoscaling for:
# - Management cluster (OCP/IPI) worker nodes via MachineSets
# - Hosted cluster NodePools
#
# USAGE:
#   # Show current utilization and scaling options (default)
#   ./.github/scripts/hypershift/setup-autoscaling.sh
#
#   # Configure management cluster autoscaling (generates commands for review)
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3
#
#   # Configure NodePool autoscaling
#   ./.github/scripts/hypershift/setup-autoscaling.sh --nodepool-max 6
#
#   # Apply the generated commands
#   ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-max 3 --apply
#
# OPTIONS:
#   --nodepool-min N     Minimum nodes for hosted cluster NodePool (default: current replicas)
#   --nodepool-max N     Maximum nodes for hosted cluster NodePool
#   --mgmt-min N         Minimum workers per MachineSet (default: 1)
#   --mgmt-max N         Maximum workers per MachineSet (e.g., 3 means up to 3 per zone)
#   --apply              Actually run the commands (default: dry-run, just print)
#   --help               Show this help message
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
APPLY=false

show_help() {
    head -35 "$0" | tail -30 | sed 's/^#//' | sed 's/^ //'
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --nodepool-min) NODEPOOL_MIN="$2"; shift 2 ;;
        --nodepool-max) NODEPOOL_MAX="$2"; shift 2 ;;
        --mgmt-min) MGMT_MIN="$2"; shift 2 ;;
        --mgmt-max) MGMT_MAX="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --help|-h) show_help ;;
        *) log_error "Unknown option: $1"; show_help ;;
    esac
done

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

declare -a NODE_NAMES=()
declare -a NODE_ROLES=()
declare -a NODE_INSTANCE=()
declare -a NODE_CPU_REQ=()
declare -a NODE_CPU_LIM=()
declare -a NODE_MEM_REQ=()
declare -a NODE_MEM_LIM=()

# Parse node information
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    name=$(echo "$line" | awk '{print $1}')
    NODE_NAMES+=("$name")

    roles=$(oc get node "$name" -o jsonpath='{.metadata.labels}' 2>/dev/null | grep -o '"node-role.kubernetes.io/[^"]*"' | sed 's/"node-role.kubernetes.io\///g; s/"//g' | tr '\n' ',' | sed 's/,$//')
    if [[ "$roles" == *"master"* ]] || [[ "$roles" == *"control-plane"* ]]; then
        NODE_ROLES+=("control-plane")
    else
        NODE_ROLES+=("worker")
    fi

    instance=$(oc get node "$name" -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type}' 2>/dev/null || echo "unknown")
    NODE_INSTANCE+=("$instance")
done < <(oc get nodes -o custom-columns='NAME:.metadata.name' --no-headers 2>/dev/null)

# Get resource allocation per node
for name in "${NODE_NAMES[@]}"; do
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

    NODE_CPU_REQ+=("$cpu_req")
    NODE_CPU_LIM+=("$cpu_lim")
    NODE_MEM_REQ+=("$mem_req")
    NODE_MEM_LIM+=("$mem_lim")
done

# Print node table
echo -e "${BOLD}Management Cluster Nodes:${NC}"
echo ""
echo "  Req = Requests (affects scheduling), Lim = Limits (affects throttling)"
echo ""
printf "  %-28s %-13s %-11s %-9s %-9s %-9s %-9s\n" "NODE" "ROLE" "INSTANCE" "CPU Req" "CPU Lim" "MEM Req" "MEM Lim"
printf "  %-28s %-13s %-11s %-9s %-9s %-9s %-9s\n" "----------------------------" "-------------" "-----------" "---------" "---------" "---------" "---------"

WORKER_COUNT=0
CONTROL_PLANE_COUNT=0
HIGH_UTIL_WORKERS=0

for i in "${!NODE_NAMES[@]}"; do
    name="${NODE_NAMES[$i]}"
    short_name=$(echo "$name" | sed 's/.ec2.internal//' | cut -c1-27)
    role="${NODE_ROLES[$i]}"
    instance="${NODE_INSTANCE[$i]}"
    cpu_req="${NODE_CPU_REQ[$i]}"
    cpu_lim="${NODE_CPU_LIM[$i]}"
    mem_req="${NODE_MEM_REQ[$i]}"
    mem_lim="${NODE_MEM_LIM[$i]}"

    cpu_num=$(echo "$cpu_req" | grep -o '[0-9]*' | head -1 || echo "0")
    if [[ "$cpu_num" -ge 80 ]] && [[ "$role" == "worker" ]]; then
        ((HIGH_UTIL_WORKERS++)) || true
    fi

    if [[ "$role" == "worker" ]]; then
        ((WORKER_COUNT++)) || true
    else
        ((CONTROL_PLANE_COUNT++)) || true
    fi

    cpu_req_c=$(colorize_pct "$cpu_req")
    cpu_lim_c=$(colorize_pct "$cpu_lim")
    mem_req_c=$(colorize_pct "$mem_req")
    mem_lim_c=$(colorize_pct "$mem_lim")

    printf "  %-28s %-13s %-11s %-20b %-20b %-20b %-20b\n" "$short_name" "$role" "$instance" "$cpu_req_c" "$cpu_lim_c" "$mem_req_c" "$mem_lim_c"
done

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

HOSTED_CLUSTERS=$(oc get hostedclusters -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || echo "")
NODEPOOL_NAME=""
NODEPOOL_NS=""
NODEPOOL_CURRENT_REPLICAS="2"

if [[ -z "$HOSTED_CLUSTERS" ]]; then
    log_warn "No hosted clusters found"
else
    echo -e "${BOLD}Hosted Clusters & NodePools:${NC}"
    echo ""
    printf "  %-38s %-10s %-10s %-12s %-10s\n" "NODEPOOL" "DESIRED" "CURRENT" "AUTOSCALING" "MIN/MAX"
    printf "  %-38s %-10s %-10s %-12s %-10s\n" "--------------------------------------" "----------" "----------" "------------" "----------"

    while IFS= read -r hc; do
        [[ -z "$hc" ]] && continue
        ns=$(echo "$hc" | cut -d'/' -f1)

        while IFS= read -r np_name; do
            [[ -z "$np_name" ]] && continue

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
        done < <(oc get nodepools -n "$ns" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
    done <<< "$HOSTED_CLUSTERS"
    echo ""
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
            echo ""

            echo "  # Step 1: Create ClusterAutoscaler"
            CA_CMD="oc apply -f - <<'EOF'
apiVersion: autoscaling.openshift.io/v1
kind: ClusterAutoscaler
metadata:
  name: default
spec:
  podPriorityThreshold: -10
  resourceLimits:
    maxNodesTotal: ${MAX_TOTAL}
  scaleDown:
    enabled: true
    delayAfterAdd: 10m
    delayAfterDelete: 5m
    delayAfterFailure: 3m
    unneededTime: 10m
EOF"
            log_cmd "$CA_CMD"
            echo ""

            if [[ "$APPLY" == "true" ]]; then
                eval "$CA_CMD"
                log_success "ClusterAutoscaler created/updated"
                echo ""
            fi

            echo "  # Step 2: Create MachineAutoscaler for each worker MachineSet"
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
  minReplicas: ${MGMT_MIN}
  maxReplicas: ${MGMT_MAX}
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
        log_success "Done! Verify with:"
        echo ""
        echo "    oc get clusterautoscaler"
        echo "    oc get machineautoscaler -n openshift-machine-api"
        [[ -n "$NODEPOOL_NAME" ]] && echo "    oc get nodepool -n clusters"
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

        # Option 2: Autoscaling
        echo -e "${BOLD}[2] ENABLE AUTOSCALING${NC} — automatic scaling (min=${MGMT_MIN}/zone, max=2/zone)"
        echo ""
        echo "    # Preview what will be created:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 2"
        echo ""
        echo "    # Apply autoscaling:"
        echo "    ./.github/scripts/hypershift/setup-autoscaling.sh --mgmt-min 1 --mgmt-max 2 --apply"
        echo ""

        # Rollback
        echo -e "${BOLD}[3] ROLLBACK AUTOSCALING${NC} — remove autoscaler config"
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
        echo -e "${BOLD}[4] NODEPOOL AUTOSCALING${NC} — scale hosted cluster workers"
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
