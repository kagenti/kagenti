#!/bin/bash
# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -eo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
MAX_ITERATIONS="${MAX_ITERATIONS:-20}"     # Maximum number of health check iterations
POLL_INTERVAL="${POLL_INTERVAL:-15}"       # Seconds between checks
TIMEOUT=$((MAX_ITERATIONS * POLL_INTERVAL)) # Total timeout

echo "===================================================================="
echo "  Kagenti Deployment Health Monitor"
echo "===================================================================="
echo ""
echo "Configuration:"
echo "  Max Iterations: $MAX_ITERATIONS"
echo "  Poll Interval: ${POLL_INTERVAL}s"
echo "  Total Timeout: ${TIMEOUT}s ($(($TIMEOUT / 60))m)"
echo ""

START_TIME=$(date +%s)
ITERATION=0

# Function to show resource usage
show_resource_usage() {
    echo ""
    echo -e "${CYAN}━━━ Resource Usage ━━━${NC}"

    # Memory
    if [ -f /proc/meminfo ]; then
        MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        MEM_AVAILABLE=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
        MEM_USED=$((MEM_TOTAL - MEM_AVAILABLE))
        MEM_USED_GB=$(awk "BEGIN {printf \"%.2f\", $MEM_USED / 1024 / 1024}")
        MEM_TOTAL_GB=$(awk "BEGIN {printf \"%.2f\", $MEM_TOTAL / 1024 / 1024}")
        MEM_PCT=$(awk "BEGIN {printf \"%.1f\", ($MEM_USED * 100) / $MEM_TOTAL}")

        local mem_color=$GREEN
        (( $(awk "BEGIN {print ($MEM_PCT > 85)}") )) && mem_color=$RED
        (( $(awk "BEGIN {print ($MEM_PCT > 70 && $MEM_PCT <= 85)}") )) && mem_color=$YELLOW

        printf "${mem_color}  Memory: ${MEM_USED_GB}/${MEM_TOTAL_GB} GB (${MEM_PCT}%% used)${NC}\n"
    fi

    # Disk usage
    if command -v df &>/dev/null; then
        DISK_INFO=$(df -h / | tail -1)
        DISK_USED=$(echo "$DISK_INFO" | awk '{print $3}')
        DISK_TOTAL=$(echo "$DISK_INFO" | awk '{print $2}')
        DISK_PCT=$(echo "$DISK_INFO" | awk '{print $5}' | tr -d '%')

        local disk_color=$GREEN
        (( DISK_PCT > 85 )) && disk_color=$RED
        (( DISK_PCT > 70 && DISK_PCT <= 85 )) && disk_color=$YELLOW

        printf "${disk_color}  Disk: ${DISK_USED}/${DISK_TOTAL} (${DISK_PCT}%% used)${NC}\n"
    fi

    # CPU load
    if [ -f /proc/loadavg ]; then
        LOAD=$(cat /proc/loadavg | awk '{print $1" "$2" "$3}')
        printf "  Load Avg (1/5/15m): ${LOAD}\n"
    fi

    # Docker containers
    if command -v docker &>/dev/null; then
        CONTAINERS=$(docker ps -q 2>/dev/null | wc -l | tr -d ' ')
        printf "  Docker Containers: ${CONTAINERS} running\n"
    fi
}

# Function to show deployment status
show_deployment_status() {
    echo ""
    echo -e "${CYAN}━━━ Deployment Status ━━━${NC}"

    local all_ready=0
    local has_errors=0

    # Check weather-tool
    if kubectl get deployment weather-tool -n team1 &>/dev/null; then
        local ready=$(kubectl get deployment weather-tool -n team1 -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        local desired=$(kubectl get deployment weather-tool -n team1 -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

        if [ "$ready" -eq "$desired" ] && [ "$ready" -gt 0 ]; then
            echo -e "${GREEN}  ✓ weather-tool: ${ready}/${desired} ready${NC}"
        else
            echo -e "${YELLOW}  ⏳ weather-tool: ${ready}/${desired} ready${NC}"
            has_errors=1
        fi
    else
        echo -e "${YELLOW}  ⏳ weather-tool: deployment not found${NC}"
        has_errors=1
    fi

    # Check weather-service
    if kubectl get deployment weather-service -n team1 &>/dev/null; then
        local ready=$(kubectl get deployment weather-service -n team1 -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        local desired=$(kubectl get deployment weather-service -n team1 -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

        if [ "$ready" -eq "$desired" ] && [ "$ready" -gt 0 ]; then
            echo -e "${GREEN}  ✓ weather-service: ${ready}/${desired} ready${NC}"
        else
            echo -e "${YELLOW}  ⏳ weather-service: ${ready}/${desired} ready${NC}"
            has_errors=1
        fi
    else
        echo -e "${YELLOW}  ⏳ weather-service: deployment not found${NC}"
        has_errors=1
    fi

    # Check Keycloak
    if kubectl get namespace keycloak &>/dev/null; then
        if kubectl get deployment keycloak -n keycloak &>/dev/null; then
            local ready=$(kubectl get deployment keycloak -n keycloak -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired=$(kubectl get deployment keycloak -n keycloak -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

            if [ "$ready" -eq "$desired" ] && [ "$ready" -gt 0 ]; then
                echo -e "${GREEN}  ✓ keycloak: ${ready}/${desired} ready${NC}"
            else
                echo -e "${YELLOW}  ⏳ keycloak: ${ready}/${desired} ready${NC}"
                has_errors=1
            fi
        elif kubectl get statefulset keycloak -n keycloak &>/dev/null; then
            local ready=$(kubectl get statefulset keycloak -n keycloak -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired=$(kubectl get statefulset keycloak -n keycloak -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

            if [ "$ready" -eq "$desired" ] && [ "$ready" -gt 0 ]; then
                echo -e "${GREEN}  ✓ keycloak: ${ready}/${desired} ready${NC}"
            else
                echo -e "${YELLOW}  ⏳ keycloak: ${ready}/${desired} ready${NC}"
                has_errors=1
            fi
        fi
    fi

    # Check Platform Operator
    if kubectl get deployment -n kagenti-system -l control-plane=controller-manager &>/dev/null; then
        local ready=$(kubectl get deployment -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "$ready" -gt 0 ]; then
            echo -e "${GREEN}  ✓ platform-operator: ${ready} ready${NC}"
        else
            echo -e "${YELLOW}  ⏳ platform-operator: not ready${NC}"
            has_errors=1
        fi
    fi

    return $has_errors
}

# Function to show pod health summary
show_pod_summary() {
    echo ""
    echo -e "${CYAN}━━━ Pod Health Summary ━━━${NC}"

    # Count pods by state
    local total=0
    local running=0
    local pending=0
    local failed=0
    local crashloop=0

    while IFS= read -r line; do
        total=$((total + 1))
        local status=$(echo "$line" | awk '{print $4}')
        local ready=$(echo "$line" | awk '{print $3}')

        case "$status" in
            Running)
                running=$((running + 1))
                ;;
            Pending)
                pending=$((pending + 1))
                ;;
            Failed|Error)
                failed=$((failed + 1))
                ;;
            *BackOff*)
                crashloop=$((crashloop + 1))
                ;;
        esac
    done < <(kubectl get pods --all-namespaces --no-headers 2>/dev/null)

    printf "  Total Pods: ${total}\n"
    printf "${GREEN}  Running: ${running}${NC}\n"
    [ "$pending" -gt 0 ] && printf "${YELLOW}  Pending: ${pending}${NC}\n"
    [ "$failed" -gt 0 ] && printf "${RED}  Failed: ${failed}${NC}\n"
    [ "$crashloop" -gt 0 ] && printf "${RED}  CrashLoop: ${crashloop}${NC}\n"

    return $(( failed + crashloop ))
}

# Function to show pod list
show_pod_list() {
    echo ""
    echo -e "${CYAN}━━━ Pod Status List ━━━${NC}"

    # Get all pods with namespace, name, ready, status, restarts
    kubectl get pods --all-namespaces -o wide 2>/dev/null | head -1  # Header

    while IFS= read -r line; do
        local ns=$(echo "$line" | awk '{print $1}')
        local pod=$(echo "$line" | awk '{print $2}')
        local ready=$(echo "$line" | awk '{print $3}')
        local status=$(echo "$line" | awk '{print $4}')
        local restarts=$(echo "$line" | awk '{print $5}')
        local age=$(echo "$line" | awk '{print $6}')

        # Color based on status
        local color=$GREEN
        case "$status" in
            Running)
                # Check if all containers are ready (safely)
                if [[ "$ready" == *"/"* ]]; then
                    local ready_count="${ready%/*}"
                    local total_count="${ready#*/}"
                    # Only compare if both are numbers
                    if [[ "$ready_count" =~ ^[0-9]+$ ]] && [[ "$total_count" =~ ^[0-9]+$ ]]; then
                        if [ "$ready_count" -ne "$total_count" ]; then
                            color=$YELLOW
                        fi
                    fi
                fi
                ;;
            Completed|Succeeded)
                color=$GREEN
                ;;
            Pending|ContainerCreating)
                color=$YELLOW
                ;;
            *)
                color=$RED
                ;;
        esac

        # Highlight pods with high restart count (safely extract number)
        local restart_num=$(echo "$restarts" | grep -oE '^[0-9]+' || echo "0")
        if [ "$restart_num" -gt 3 ] 2>/dev/null; then
            color=$RED
        fi

        printf "${color}%-20s %-50s %-15s %-20s %s${NC}\n" \
            "$ns" "$pod" "$ready" "$status" "Restarts: $restarts"

    done < <(kubectl get pods --all-namespaces --no-headers 2>/dev/null | sort -k1,1 -k4,4r)
}

# Function to show failed pods with details
show_failed_pods() {
    local failed_pods=$(kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null)

    if [ -z "$failed_pods" ]; then
        return 0
    fi

    echo ""
    echo -e "${RED}━━━ Failed Pods Details ━━━${NC}"

    while IFS= read -r line; do
        local ns=$(echo "$line" | awk '{print $1}')
        local pod=$(echo "$line" | awk '{print $2}')
        local status=$(echo "$line" | awk '{print $4}')

        echo -e "${RED}  ✗ $ns/$pod: $status${NC}"

        # Get recent events
        local events=$(kubectl get events -n "$ns" --field-selector involvedObject.name="$pod" --sort-by='.lastTimestamp' 2>/dev/null | tail -3 | tail -n +2)
        if [ -n "$events" ]; then
            echo -e "${YELLOW}    Events:${NC}"
            echo "$events" | while IFS= read -r event; do
                echo -e "${YELLOW}      - $(echo "$event" | awk '{print $4": "$5" "$6" "$7" "$8" "$9" "$10}')${NC}"
            done
        fi

        # Get container errors from logs
        local error_logs=$(kubectl logs -n "$ns" "$pod" --all-containers=true --tail=10 2>&1 | grep -iE "error|fatal|panic|exception" | head -5)
        if [ -n "$error_logs" ]; then
            echo -e "${RED}    Error logs:${NC}"
            echo "$error_logs" | while IFS= read -r log_line; do
                echo -e "${RED}      $(echo "$log_line" | cut -c1-120)${NC}"
            done
        fi

        echo ""
    done <<< "$failed_pods"

    return 1
}

# Function to check if deployment is healthy
check_health() {
    local is_healthy=0

    # Check 1: No failed pods
    local failed_count=$(kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$failed_count" -gt 0 ]; then
        is_healthy=1
    fi

    # Check 2: No crashlooping pods
    local crashloop_count=$(kubectl get pods --all-namespaces -o json 2>/dev/null | jq -r '[.items[] | select(.status.containerStatuses[]? | .restartCount > 3)] | length')
    if [ "$crashloop_count" -gt 0 ]; then
        is_healthy=1
    fi

    # Check 3: Critical deployments ready
    show_deployment_status > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        is_healthy=1
    fi

    return $is_healthy
}

# Main monitoring loop
while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    ELAPSED=$(($(date +%s) - START_TIME))

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${CYAN}Health Check Iteration ${ITERATION}/${MAX_ITERATIONS} (${ELAPSED}s elapsed)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    show_resource_usage
    show_deployment_status
    deployment_status=$?

    show_pod_summary
    pod_status=$?

    show_pod_list

    # Check overall health
    if [ $deployment_status -eq 0 ] && [ $pod_status -eq 0 ]; then
        # Double-check with detailed health check
        if check_health; then
            echo ""
            echo "===================================================================="
            echo -e "${GREEN}✓ Deployment is HEALTHY${NC}"
            echo "===================================================================="
            echo ""
            echo "  All deployments ready:"
            echo "    • weather-tool"
            echo "    • weather-service"
            echo "    • keycloak"
            echo "    • platform-operator"
            echo ""
            echo "  No failed or crashlooping pods"
            echo ""
            echo "  Time to healthy: ${ELAPSED}s ($(($ELAPSED / 60))m)"
            echo ""
            exit 0
        fi
    fi

    # Show failures if any
    if [ $pod_status -ne 0 ]; then
        show_failed_pods
    fi

    # Check if we've exceeded timeout
    if [ $ITERATION -ge $MAX_ITERATIONS ]; then
        echo ""
        echo "===================================================================="
        echo -e "${RED}✗ Deployment is UNHEALTHY${NC}"
        echo "===================================================================="
        echo ""
        echo -e "${RED}Reason: Timeout reached (${TIMEOUT}s) without achieving healthy state${NC}"
        echo ""
        show_failed_pods
        echo ""
        exit 1
    fi

    # Wait before next iteration
    echo ""
    echo -e "${YELLOW}Waiting ${POLL_INTERVAL}s before next check...${NC}"
    sleep $POLL_INTERVAL
done

# If we exit the loop without success, fail
echo ""
echo "===================================================================="
echo -e "${RED}✗ Deployment is UNHEALTHY${NC}"
echo "===================================================================="
echo ""
echo -e "${RED}Reason: Maximum iterations reached without achieving healthy state${NC}"
echo ""
show_failed_pods
echo ""
exit 1
