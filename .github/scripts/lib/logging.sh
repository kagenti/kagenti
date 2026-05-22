#!/usr/bin/env bash
# Logging Library
# Provides color output, logging functions, and common utilities

# Color codes
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export NC='\033[0m' # No Color

# Log header with box
log_header() {
    local message="$1"
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════════════════════════════════╗"
    printf "║ %-62s ║\n" "$message"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Log step with sync wave number
log_step() {
    local wave="$1"
    local description="$2"
    echo -e "${BLUE}[Wave $wave] $description${NC}"
}

# Log success message
log_success() {
    local message="$1"
    echo -e "${GREEN}✓ $message${NC}"
}

# Log error message
log_error() {
    local message="$1"
    echo -e "${RED}✗ $message${NC}"
}

# Log info message
log_info() {
    local message="$1"
    echo -e "${CYAN}ℹ $message${NC}"
}

# Log warning message
log_warn() {
    local message="$1"
    echo -e "${YELLOW}⚠ $message${NC}"
}

# Cross-platform date parsing (Linux GNU date vs macOS BSD date)
# Converts ISO 8601 date (e.g., "2024-01-15T10:30:00Z") to epoch seconds
parse_iso_date() {
    local iso_date="$1"
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS BSD date
        date -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso_date" +%s 2>/dev/null || echo "0"
    else
        # Linux GNU date
        date -d "$iso_date" +%s 2>/dev/null || echo "0"
    fi
}
