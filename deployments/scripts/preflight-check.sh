#!/usr/bin/env bash
#
# Kagenti OpenShift Pre-flight Check Script
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# This script validates the OpenShift environment before Kagenti installation
# It checks version compatibility, required tools, and cluster readiness
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Minimum version requirements
MIN_OCP_VERSION="4.16.0"
MIN_OCP_VERSION_FOR_SPIRE="4.19.0"
MIN_HELM_VERSION="3.18.0"
MIN_KUBECTL_VERSION="1.32.1"

# Check results
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

# Function to print section headers
print_header() {
    echo -e "\n${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${BLUE}$1${NC}"
    echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Function to print check results
print_check() {
    local status=$1
    local message=$2
    
    case $status in
        "PASS")
            echo -e "${GREEN}✓${NC} $message"
            CHECKS_PASSED=$((CHECKS_PASSED + 1))
            ;;
        "FAIL")
            echo -e "${RED}✗${NC} $message"
            CHECKS_FAILED=$((CHECKS_FAILED + 1))
            ;;
        "WARN")
            echo -e "${YELLOW}⚠${NC} $message"
            CHECKS_WARNING=$((CHECKS_WARNING + 1))
            ;;
        "INFO")
            echo -e "${BLUE}ℹ${NC} $message"
            ;;
    esac
}

# Function to compare versions
version_compare() {
    local version1=$1
    local version2=$2
    
    # Remove 'v' prefix if present
    version1=${version1#v}
    version2=${version2#v}
    
    # Split versions into arrays
    IFS='.' read -ra ver1 <<< "$version1"
    IFS='.' read -ra ver2 <<< "$version2"
    
    # Compare major, minor, patch
    for i in 0 1 2; do
        local v1=${ver1[$i]:-0}
        local v2=${ver2[$i]:-0}
        
        if ((v1 > v2)); then
            return 0  # version1 > version2
        elif ((v1 < v2)); then
            return 1  # version1 < version2
        fi
    done
    
    return 0  # versions are equal
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Main checks
main() {
    print_header "Kagenti OpenShift Pre-flight Checks"
    echo -e "Validating environment for Kagenti installation...\n"
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Check Required Tools
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_header "Required Tools"
    
    # Check kubectl/oc
    if command_exists oc; then
        if command_exists jq; then
            OC_VERSION=$(oc version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion' 2>/dev/null || echo "unknown")
        else
            OC_VERSION=$(oc version --client 2>/dev/null | head -n1 || echo "unknown")
        fi
        print_check "PASS" "oc CLI found: $OC_VERSION"
    elif command_exists kubectl; then
        if command_exists jq; then
            KUBECTL_VERSION=$(kubectl version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion' 2>/dev/null || echo "unknown")
        else
            KUBECTL_VERSION=$(kubectl version --client 2>/dev/null | head -n1 || echo "unknown")
        fi
        print_check "PASS" "kubectl found: $KUBECTL_VERSION"
    else
        print_check "FAIL" "Neither 'oc' nor 'kubectl' found. Please install OpenShift CLI or kubectl."
    fi
    
    # Check helm
    if command_exists helm; then
        HELM_VERSION=$(helm version --short 2>/dev/null | sed -n 's/.*v\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' || echo "unknown")
        if [[ "$HELM_VERSION" != "unknown" ]] && version_compare "$HELM_VERSION" "$MIN_HELM_VERSION"; then
            print_check "PASS" "Helm found: v$HELM_VERSION (>= v$MIN_HELM_VERSION)"
        else
            print_check "WARN" "Helm found: v$HELM_VERSION (recommended: >= v$MIN_HELM_VERSION)"
        fi
    else
        print_check "FAIL" "Helm not found. Please install Helm >= v$MIN_HELM_VERSION"
    fi
    
    # Check jq
    if command_exists jq; then
        print_check "PASS" "jq found"
    else
        print_check "WARN" "jq not found (optional but recommended for JSON parsing)"
    fi
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Check Cluster Connectivity
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_header "Cluster Connectivity"
    
    if command_exists kubectl || command_exists oc; then
        CLI_CMD=$(command_exists oc && echo "oc" || echo "kubectl")
        
        if $CLI_CMD cluster-info >/dev/null 2>&1; then
            print_check "PASS" "Connected to cluster"
            
            # Check admin permissions
            if $CLI_CMD auth can-i create namespace >/dev/null 2>&1; then
                print_check "PASS" "Admin permissions verified"
            else
                print_check "FAIL" "Insufficient permissions. Admin access required for installation."
            fi
        else
            print_check "FAIL" "Cannot connect to cluster. Please check your kubeconfig."
        fi
    fi
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Check OpenShift Version
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_header "OpenShift Version Compatibility"
    
    OCP_VERSION=""
    if command_exists oc && command_exists jq; then
        OCP_VERSION=$(oc version -o json 2>/dev/null | jq -r '.openshiftVersion // empty' 2>/dev/null || echo "")
    fi
    
    if [[ -z "$OCP_VERSION" ]] && (command_exists kubectl || command_exists oc); then
        CLI_CMD=$(command_exists oc && echo "oc" || echo "kubectl")
        OCP_VERSION=$($CLI_CMD get clusterversion version -o jsonpath='{.status.desired.version}' 2>/dev/null || echo "")
    fi
    
    if [[ -n "$OCP_VERSION" ]]; then
        print_check "INFO" "Detected OpenShift version: $OCP_VERSION"
        
        # Check minimum version for Kagenti
        if version_compare "$OCP_VERSION" "$MIN_OCP_VERSION"; then
            print_check "PASS" "OpenShift version >= $MIN_OCP_VERSION (Kagenti compatible)"
        else
            print_check "FAIL" "OpenShift version < $MIN_OCP_VERSION (minimum required for Kagenti)"
        fi
        
        # Check version for SPIRE/ZTWIM
        if version_compare "$OCP_VERSION" "$MIN_OCP_VERSION_FOR_SPIRE"; then
            print_check "PASS" "OpenShift version >= $MIN_OCP_VERSION_FOR_SPIRE (SPIRE/ZTWIM supported)"
            echo -e "  ${GREEN}→${NC} SPIRE/ZTWIM operator can be enabled"
        else
            print_check "WARN" "OpenShift version < $MIN_OCP_VERSION_FOR_SPIRE (SPIRE/ZTWIM not available)"
            echo -e "  ${YELLOW}→${NC} SPIRE will be automatically disabled during installation"
            echo -e "  ${YELLOW}→${NC} To enable SPIRE, upgrade to OpenShift $MIN_OCP_VERSION_FOR_SPIRE or higher"
            echo -e "  ${YELLOW}→${NC} See: docs/ocp/openshift-install.md for upgrade instructions"
        fi
    else
        print_check "WARN" "Unable to detect OpenShift version"
        echo -e "  ${YELLOW}→${NC} Version validation will occur during installation"
    fi
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Check Network Configuration
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_header "Network Configuration"
    
    if command_exists kubectl || command_exists oc; then
        CLI_CMD=$(command_exists oc && echo "oc" || echo "kubectl")
        
        NETWORK_TYPE=$($CLI_CMD get network.config/cluster -o jsonpath='{.status.networkType}' 2>/dev/null || echo "unknown")
        if [[ "$NETWORK_TYPE" != "unknown" ]]; then
            print_check "INFO" "Network type: $NETWORK_TYPE"
            
            if [[ "$NETWORK_TYPE" == "OVNKubernetes" ]]; then
                print_check "WARN" "OVNKubernetes detected - may require routingViaHost configuration for Istio Ambient"
                echo -e "  ${YELLOW}→${NC} See: docs/ocp/openshift-install.md#check-cluster-network-type-and-configure-for-ovn-in-ambient-mode"
            fi
        fi
    fi
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Summary
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print_header "Pre-flight Check Summary"
    
    echo -e "${GREEN}Passed:${NC}   $CHECKS_PASSED"
    echo -e "${YELLOW}Warnings:${NC} $CHECKS_WARNING"
    echo -e "${RED}Failed:${NC}   $CHECKS_FAILED"
    
    echo ""
    if [[ $CHECKS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}✓ Pre-flight checks completed successfully!${NC}"
        echo -e "You can proceed with Kagenti installation."
        echo ""
        echo -e "Next steps:"
        echo -e "  1. Review any warnings above"
        echo -e "  2. Run the OCP installer: ${BLUE}scripts/ocp/setup-kagenti.sh${NC}"
        echo -e "  3. Or install manually with Helm (see docs/ocp/openshift-install.md)"
        exit 0
    else
        echo -e "${RED}${BOLD}✗ Pre-flight checks failed!${NC}"
        echo -e "Please resolve the issues above before proceeding with installation."
        echo ""
        echo -e "For help, see: ${BLUE}docs/ocp/openshift-install.md${NC}"
        exit 1
    fi
}

# Run main function
main "$@"

# Made with Bob
