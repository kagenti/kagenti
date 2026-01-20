#!/usr/bin/env bash
# Download hcp CLI from management cluster (faster than building from source)
set -euo pipefail

echo "Downloading hcp CLI from management cluster..."

# Get download URL from consoleclidownloads CRD
HCP_DOWNLOAD_URL=$(oc get consoleclidownloads hcp-cli-download \
    -o jsonpath='{.spec.links[?(@.text=="Download hcp CLI for Linux for x86_64")].href}' 2>/dev/null || echo "")

if [ -z "$HCP_DOWNLOAD_URL" ]; then
    echo "Warning: Could not find hcp CLI download URL, building from source..."
    git clone --depth 1 https://github.com/openshift/hypershift.git /tmp/hypershift
    cd /tmp/hypershift
    make product-cli
    sudo mv bin/hcp /usr/local/bin/hcp
    sudo chmod +x /usr/local/bin/hcp
    rm -rf /tmp/hypershift
else
    echo "Downloading from: $HCP_DOWNLOAD_URL"
    # Get bearer token for authenticated download
    # Use -k to skip SSL verification (cluster uses self-signed certs)
    TOKEN=$(oc whoami -t 2>/dev/null || echo "")
    if [ -n "$TOKEN" ]; then
        curl -fsSLk -H "Authorization: Bearer $TOKEN" -o /tmp/hcp.tar.gz "$HCP_DOWNLOAD_URL"
    else
        curl -fsSLk -o /tmp/hcp.tar.gz "$HCP_DOWNLOAD_URL"
    fi
    # Extract to temp dir and find hcp binary (archive structure varies)
    mkdir -p /tmp/hcp-extract
    tar -xzf /tmp/hcp.tar.gz -C /tmp/hcp-extract
    echo "Archive contents:"
    find /tmp/hcp-extract -type f -name 'hcp*' | head -5
    HCP_BIN=$(find /tmp/hcp-extract -type f -name 'hcp' | head -1)
    if [ -z "$HCP_BIN" ]; then
        echo "Error: hcp binary not found in archive"
        exit 1
    fi
    sudo mv "$HCP_BIN" /usr/local/bin/hcp
    sudo chmod +x /usr/local/bin/hcp
    rm -rf /tmp/hcp.tar.gz /tmp/hcp-extract
fi

echo "hcp CLI installed:"
hcp version
