#!/usr/bin/env bash
# Install required tools for HyperShift CI
set -euo pipefail

echo "Installing tools..."

# Install oc CLI
curl -fsSL -o /tmp/oc.tar.gz \
    "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OCP_VERSION}/openshift-client-linux.tar.gz"
sudo tar -xzf /tmp/oc.tar.gz -C /usr/local/bin oc kubectl
sudo chmod +x /usr/local/bin/oc /usr/local/bin/kubectl
rm /tmp/oc.tar.gz

# Install ansible
pip install ansible-core kubernetes openshift PyYAML

# Install ansible collections (community.aws required for sts_session_token)
# Retry loop for transient Ansible Galaxy failures (HTTP 500)
MAX_RETRIES=5
RETRY_DELAY=30
for i in $(seq 1 $MAX_RETRIES); do
    echo "Attempt $i/$MAX_RETRIES: Installing Ansible collections..."
    if ansible-galaxy collection install kubernetes.core amazon.aws community.aws community.general; then
        echo "Ansible collections installed successfully"
        break
    else
        if [ "$i" -eq "$MAX_RETRIES" ]; then
            echo "Failed to install Ansible collections after $MAX_RETRIES attempts"
            exit 1
        fi
        echo "Ansible Galaxy failed (attempt $i/$MAX_RETRIES), retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    fi
done

echo "Tools installed:"
oc version --client
ansible --version | head -1
