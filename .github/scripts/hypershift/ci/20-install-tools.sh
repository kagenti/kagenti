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
ansible-galaxy collection install kubernetes.core amazon.aws community.aws community.general

echo "Tools installed:"
oc version --client
ansible --version | head -1
