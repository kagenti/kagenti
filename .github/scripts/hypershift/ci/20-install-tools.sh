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
# Try Galaxy first with retries, fall back to GitHub if Galaxy is down
install_collections_galaxy() {
    local MAX_RETRIES=3
    local RETRY_DELAY=15
    for i in $(seq 1 $MAX_RETRIES); do
        echo "Galaxy attempt $i/$MAX_RETRIES: Installing Ansible collections..."
        if ansible-galaxy collection install kubernetes.core amazon.aws community.aws community.general 2>&1; then
            echo "Ansible collections installed from Galaxy"
            return 0
        fi
        echo "Galaxy failed (attempt $i/$MAX_RETRIES), retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    done
    return 1
}

install_collections_github() {
    echo "Installing Ansible collections from GitHub (Galaxy fallback)..."
    # Install from GitHub repos when Galaxy is down
    ansible-galaxy collection install git+https://github.com/ansible-collections/kubernetes.core.git,main --force && \
    ansible-galaxy collection install git+https://github.com/ansible-collections/amazon.aws.git,main --force && \
    ansible-galaxy collection install git+https://github.com/ansible-collections/community.aws.git,main --force && \
    ansible-galaxy collection install git+https://github.com/ansible-collections/community.general.git,main --force
}

if ! install_collections_galaxy; then
    echo "Ansible Galaxy unavailable, falling back to GitHub..."
    if ! install_collections_github; then
        echo "Failed to install Ansible collections from both Galaxy and GitHub"
        exit 1
    fi
    echo "Ansible collections installed from GitHub"
fi

echo "Tools installed:"
oc version --client
ansible --version | head -1
