#!/usr/bin/env bash
# Clone hypershift-automation repository
set -euo pipefail

echo "Cloning hypershift-automation..."

# Clone from Ladas fork with additional tags support
git clone --branch add-additional-tags-support --depth 1 \
    https://github.com/Ladas/hypershift-automation.git /tmp/hypershift-automation

echo "hypershift-automation cloned to /tmp/hypershift-automation"
