# Terraform Infrastructure for Kagenti HyperShift

This directory contains Terraform configuration for deploying an OpenShift management cluster that will run HyperShift operator with MCE 2.10 for creating OpenShift 4.20.x hosted clusters.

MCE 2.10 supports OpenShift 4.19, 4.20, and 4.21. This guide focuses on **4.20.11** which is tested and verified.

**Important:** Terraform is ONLY used for the management cluster infrastructure. Hosted clusters (sandboxes) are created using the Ansible-only approach via the standard `create-cluster.sh` script.

## Structure

```
terraform/
├── management-cluster/    # Management cluster for HyperShift
│   ├── main.tf           # VPC, subnets, networking
│   ├── variables.tf      # Configuration variables
│   ├── outputs.tf        # Infrastructure outputs
│   ├── versions.tf       # Version compatibility matrix
│   ├── scripts/          # Installation automation
│   │   ├── install-openshift.sh  # Deploy OpenShift
│   │   └── install-mce.sh        # Install MCE 2.10
│   ├── templates/        # Config templates
│   └── README.md         # Detailed documentation
└── README.md             # This file
```

## Quick Start

Deploy a new OpenShift 4.20.11 management cluster:

```bash
cd management-cluster

# Configure
cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars  # Set cluster_name, base_domain, etc.

# Deploy infrastructure
terraform init
terraform apply

# Install OpenShift (30-45 min)
./scripts/install-openshift.sh

# Install MCE 2.10 (5-10 min)
export KUBECONFIG=~/openshift-clusters/<cluster-name>/auth/kubeconfig
./scripts/install-mce.sh
```

See [management-cluster/README.md](./management-cluster/README.md) for full documentation.

## Why Two Approaches?

### Management Cluster: Terraform + openshift-install

- **Purpose**: Creates full OpenShift cluster to run HyperShift operator
- **Tools**: Terraform, openshift-install, pull secret
- **Time**: 45+ minutes
- **Cost**: ~$1,500/month
- **Use case**: Deploy once, use for months

### Hosted Clusters: Ansible-only

- **Purpose**: Creates lightweight sandbox clusters for CI/testing
- **Tools**: Ansible + hcp CLI (via `.github/scripts/hypershift/create-cluster.sh`)
- **Time**: 15 minutes
- **Cost**: Minimal (control plane runs on management cluster)
- **Use case**: Ephemeral clusters created/destroyed by CI

The `hcp create cluster aws` command always creates its own infrastructure, so Terraform cannot be used for hosted clusters.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Management Cluster (OpenShift 4.20.11)                     │
│  - Deployed via Terraform + openshift-install               │
│  - MCE 2.10 operator                                        │
│  - HyperShift operator (supports 4.19-4.21)                 │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │  Hosted Cluster 1 (4.20.x)                      │       │
│  │  - Created via Ansible (create-cluster.sh)      │       │
│  │  - Control plane: runs as pods                  │       │
│  │  - Workers: separate AWS VPC (hcp creates)      │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │  Hosted Cluster 2 (4.20.x)                      │       │
│  │  - Created via Ansible (create-cluster.sh)      │       │
│  │  - Control plane: runs as pods                  │       │
│  │  - Workers: separate AWS VPC (hcp creates)      │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Documentation

- [management-cluster/README.md](./management-cluster/README.md) - Terraform configuration details
- [versions.tf](./management-cluster/versions.tf) - OpenShift and MCE version compatibility matrix

## Next Steps

1. Deploy management cluster (see [management-cluster/README.md](./management-cluster/README.md))
2. Create hosted clusters (see [.github/scripts/hypershift/](../.github/scripts/hypershift/))
3. Set up CI workflows for automated testing

## Supported Versions

This Terraform configuration uses **MCE 2.10** which supports:
- Management cluster: OpenShift 4.19, 4.20, 4.21
- Hosted clusters: OpenShift 4.19, 4.20, 4.21

**Current tested version: 4.20.11** (used by kagenti-team management cluster)
