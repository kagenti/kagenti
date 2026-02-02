#!/usr/bin/env bash
# Clone hypershift-automation repository
set -euo pipefail

echo "Cloning hypershift-automation..."

# Clone from Ladas fork with additional tags support, VPC endpoint cleanup, and route table fix
# Using exact commit for reproducibility and safety
HYPERSHIFT_AUTOMATION_COMMIT="59ae16b"

git clone --branch add-additional-tags-support \
    https://github.com/Ladas/hypershift-automation.git /tmp/hypershift-automation

cd /tmp/hypershift-automation
git checkout "$HYPERSHIFT_AUTOMATION_COMMIT"

echo "hypershift-automation cloned to /tmp/hypershift-automation (commit: $HYPERSHIFT_AUTOMATION_COMMIT)"
