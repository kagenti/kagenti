# OpenShift Management Cluster for HyperShift

This Terraform configuration deploys an OpenShift Container Platform management cluster on AWS that will run the HyperShift operator with MCE 2.10 for creating hosted clusters.

**Tested with OpenShift 4.20.11.** MCE 2.10 supports OpenShift 4.19, 4.20, and 4.21 for both management and hosted clusters.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  OpenShift Management Cluster (4.20.11)                     │
│  - MCE 2.10 operator                                        │
│  - HyperShift operator (supports 4.19-4.21)                 │
│  - 3 control plane nodes (m6i.xlarge)                       │
│  - 3+ worker nodes (m6i.2xlarge)                            │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │  Hosted Cluster 1 (4.20.x)                      │       │
│  │  Control plane runs as pods                     │       │
│  │  Workers in separate AWS account/VPC            │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │  Hosted Cluster 2 (4.20.x)                      │       │
│  │  Control plane runs as pods                     │       │
│  │  Workers in separate AWS account/VPC            │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- **Terraform** 1.7.0 or later
- **openshift-install** CLI (matching your desired OCP version)
  - Download from: https://console.redhat.com/openshift/downloads
- **oc** CLI (OpenShift CLI)
- **AWS CLI** configured with credentials
- **Red Hat pull secret** from https://console.redhat.com/openshift/install/pull-secret
- **S3 bucket** for Terraform state (recommended for team use)
- **Route53 hosted zone** for your base domain

## Quick Start

### 1. Configure Variables

```bash
cd terraform/management-cluster

# Copy example files
cp terraform.tfvars.example terraform.tfvars
cp backend.tfvars.example backend.tfvars

# Edit with your values
vim terraform.tfvars
vim backend.tfvars
```

### 2. Initialize Terraform

```bash
# With S3 backend
terraform init -backend-config=backend.tfvars

# Or without backend (local state)
terraform init
```

### 3. Create Infrastructure

```bash
# Review plan
terraform plan

# Apply
terraform apply
```

This creates:
- VPC with public/private subnets across 3 AZs
- NAT gateways for outbound connectivity
- Route tables and security groups
- Install config template for OpenShift

### 4. Install OpenShift

```bash
./scripts/install-openshift.sh
```

This will:
- Download pull secret (or use `~/.pullsecret.json`)
- Generate SSH keypair
- Create `install-config.yaml` from Terraform outputs
- Run `openshift-install create cluster`
- Wait for installation (30-45 minutes)

### 5. Install MCE 2.10

```bash
export KUBECONFIG=~/openshift-clusters/<cluster-name>/auth/kubeconfig

./scripts/install-mce.sh
```

This will:
- Install MCE 2.10 operator via OLM
- Create MultiClusterEngine instance
- Enable HyperShift and local hosting components
- Wait for HyperShift operator to be ready

### 6. Verify Installation

```bash
# Check cluster
oc get nodes
oc get clusterversion

# Check MCE
oc get multiclusterengine

# Check HyperShift operator
oc get deployment operator -n hypershift
oc get deployment operator -n hypershift \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Creating Hosted Clusters

After MCE 2.10 is installed, you can create hosted clusters (4.19, 4.20, or 4.21):

```bash
# Configure credentials for hosted cluster creation
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-east-1"

# Create hosted cluster (via existing kagenti scripts)
cd ../../
./.github/scripts/local-setup/hypershift-full-test.sh test1 \
  --skip-cluster-destroy

# The cluster will use 4.20.11 by default (matching management cluster)
# Specify OCP_VERSION environment variable for different versions
```

## Cleanup

### Destroy Management Cluster

```bash
# First, delete all hosted clusters!
# Run destroy scripts for each hosted cluster

# Then destroy management cluster
cd ~/openshift-clusters/<cluster-name>
openshift-install destroy cluster --dir .

# Finally, destroy Terraform infrastructure
cd <repo>/terraform/management-cluster
terraform destroy
```

## Cost Estimation

AWS costs (us-east-1, approximate monthly):

| Resource | Quantity | Unit Cost | Monthly Cost |
|----------|----------|-----------|--------------|
| m6i.xlarge (control plane) | 3 | $0.192/hr | ~$414 |
| m6i.2xlarge (workers) | 3 | $0.384/hr | ~$829 |
| NAT Gateway | 3 | $0.045/hr + data | ~$100 |
| EBS (gp3) | ~1.5 TB | $0.08/GB-month | ~$120 |
| Load Balancers | 2 | $0.0225/hr | ~$33 |
| **Total** | | | **~$1,500/month** |

Each hosted cluster adds minimal cost (workers only, control plane runs on mgmt cluster).

## Troubleshooting

### OpenShift Installation Fails

Check logs:
```bash
tail -f ~/openshift-clusters/<cluster-name>/.openshift_install.log
```

Common issues:
- Route53 hosted zone not found → create hosted zone for base domain
- AWS quota limits → request quota increase
- Subnet CIDR conflicts → adjust `vpc_cidr` in tfvars

### MCE Installation Fails

Check operator status:
```bash
oc get csv -n multicluster-engine
oc logs -n multicluster-engine deployment/multicluster-engine-operator
```

### HyperShift Not Ready

Check HyperShift operator:
```bash
oc get deployment operator -n hypershift
oc logs -n hypershift deployment/operator
```

## Configuration Reference

### Instance Type Sizing

Control plane nodes (masters):
- Minimum: `m6i.xlarge` (4 vCPU, 16 GB) - for testing
- Recommended: `m6i.2xlarge` (8 vCPU, 32 GB) - for production

Worker nodes:
- Minimum: `m6i.2xlarge` (8 vCPU, 32 GB) - HyperShift requires more resources
- Recommended: `m6i.4xlarge` (16 vCPU, 64 GB) - for multiple hosted clusters

### Network Sizing

Default VPC CIDR: `10.0.0.0/16`
- Public subnets: 10.0.0.0/20, 10.0.16.0/20, 10.0.32.0/20
- Private subnets: 10.0.48.0/20, 10.0.64.0/20, 10.0.80.0/20

Adjust `vpc_cidr` in tfvars if this conflicts with your network.

## Next Steps

- Create hosted clusters using `.github/scripts/local-setup/hypershift-full-test.sh`
- Review version compatibility in [versions.tf](./versions.tf)
- Set up automation scripts in `.github/scripts/hypershift/terraform/`

## References

- [OpenShift IPI on AWS](https://docs.openshift.com/container-platform/4.20/installing/installing_aws/installing-aws-customizations.html)
- [MCE 2.10 Documentation](https://docs.redhat.com/en/documentation/red_hat_advanced_cluster_management_for_kubernetes/2.10)
- [HyperShift Documentation](https://hypershift-docs.netlify.app/)
