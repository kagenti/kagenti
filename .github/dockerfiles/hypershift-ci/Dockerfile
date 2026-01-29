# HyperShift CI Container
#
# Container image for provisioning ephemeral OpenShift clusters via HyperShift.
# Uses hypershift-automation ansible playbooks for cluster lifecycle management.
#
# BUILD:
#   docker build -t ghcr.io/kagenti/hypershift-ci:latest .
#
# USAGE:
#   docker run -v ~/.pullsecret.json:/root/.pullsecret.json \
#     -e KUBECONFIG=/tmp/mgmt -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... \
#     ghcr.io/kagenti/hypershift-ci:latest \
#     ansible-playbook site.yml -e create=true -e "additional_tags=ManagedBy=hypershift-ci" ...
#

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.4

# === PINNED VERSIONS ===
# Update these to upgrade tooling
ARG OC_VERSION=4.20.11
ARG AWS_CLI_VERSION=2.15.0
ARG GO_VERSION=1.23.5

# hypershift-automation fork with additional_tags support
# Branch: add-additional-tags-support
ARG HYPERSHIFT_AUTOMATION_REPO=https://github.com/Ladas/hypershift-automation.git
ARG HYPERSHIFT_AUTOMATION_BRANCH=add-additional-tags-support

# Install base dependencies
RUN microdnf install -y \
        python3 \
        python3-pip \
        tar \
        gzip \
        git \
        jq \
        which \
        findutils \
        make \
        unzip \
    && microdnf clean all

# Install Python packages for ansible (optional, for advanced automation)
RUN pip3 install --no-cache-dir ansible-core kubernetes openshift PyYAML

# Install oc CLI
RUN curl -fsSL -o /tmp/oc.tar.gz \
        "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OC_VERSION}/openshift-client-linux.tar.gz" && \
    tar -xzf /tmp/oc.tar.gz -C /usr/local/bin oc kubectl && \
    chmod +x /usr/local/bin/oc /usr/local/bin/kubectl && \
    rm /tmp/oc.tar.gz

# Install Go (needed to build hcp CLI)
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o /tmp/go.tar.gz && \
    tar -xzf /tmp/go.tar.gz -C /usr/local && \
    rm /tmp/go.tar.gz

ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/root/go"

# Build hcp CLI from source (no pre-built binaries available)
RUN git clone --depth 1 https://github.com/openshift/hypershift.git /tmp/hypershift && \
    cd /tmp/hypershift && \
    make product-cli && \
    mv bin/hcp /usr/local/bin/hcp && \
    chmod +x /usr/local/bin/hcp && \
    rm -rf /tmp/hypershift /root/go

# Install AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip && \
    cd /tmp && unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf /tmp/aws /tmp/awscliv2.zip

# Clone hypershift-automation with additional_tags support
RUN git clone --branch ${HYPERSHIFT_AUTOMATION_BRANCH} --depth 1 \
        ${HYPERSHIFT_AUTOMATION_REPO} /opt/hypershift-automation && \
    rm -rf /opt/hypershift-automation/.git

# Install ansible collections required by the playbook
RUN ansible-galaxy collection install kubernetes.core amazon.aws community.general

# Add playbook directory to PATH
ENV PATH="/opt/hypershift-automation:${PATH}"

# Default working directory
WORKDIR /opt/hypershift-automation

# Default entrypoint (can be overridden)
ENTRYPOINT ["/bin/bash"]

# Labels
LABEL org.opencontainers.image.title="HyperShift CI"
LABEL org.opencontainers.image.description="Container for HyperShift cluster lifecycle management in CI"
LABEL org.opencontainers.image.source="https://github.com/kagenti/kagenti"
LABEL org.opencontainers.image.vendor="Kagenti"
