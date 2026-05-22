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

### Option A: Automated Full Deployment (Recommended)

This runs Terraform, OpenShift install, and MCE install with validation:

```bash
cd terraform/management-cluster

# Initialize Terraform
terraform init

# Run full deployment (creates workspace automatically)
./scripts/deploy-full.sh terraform-kagenti-team.tfvars

# Or skip MCE installation
./scripts/deploy-full.sh terraform-kagenti-team.tfvars --skip-mce
```

The script will:
1. Create/select Terraform workspace
2. Run `terraform plan` and prompt for confirmation
3. Run `terraform apply` with full validation
4. Verify infrastructure (NAT gateways, route tables, etc.)
5. Install OpenShift (30-45 minutes)
6. Optionally install MCE 2.10 and HyperShift

### Option B: Manual Step-by-Step Deployment

If you prefer to run each step manually:

#### 1. Configure Variables

```bash
cd terraform/management-cluster

# Copy and edit your tfvars file
cp terraform.tfvars.example terraform-my-cluster.tfvars
vim terraform-my-cluster.tfvars
```

#### 2. Initialize Terraform

```bash
# Initialize (creates .terraform directory)
terraform init
```

#### 3. Create Terraform Workspace

**IMPORTANT:** Always use workspaces to isolate cluster state:

```bash
# Create and switch to workspace for your cluster
terraform workspace new my-cluster-name

# Or select existing workspace
terraform workspace select my-cluster-name
```

#### 4. Deploy Infrastructure with Terraform

```bash
# Review plan
terraform plan -var-file=terraform-my-cluster.tfvars

# Apply (this must complete fully!)
terraform apply -var-file=terraform-my-cluster.tfvars

# CRITICAL: Verify infrastructure is complete
terraform state list | wc -l
# Should show 20+ resources, not just 8

# Verify NAT gateways exist (critical for worker connectivity)
terraform state list | grep nat_gateway
# Should show 3 NAT gateways
```

This creates:
- VPC with public/private subnets across 3 AZs
- **NAT gateways for outbound connectivity** (critical!)
- Route tables and security groups
- Install config template for OpenShift

**⚠️ WARNING:** Do not proceed to OpenShift installation if Terraform state shows fewer than 20 resources. This means `terraform apply` did not complete successfully, and your cluster will be missing critical infrastructure like NAT gateways.

#### 5. Install OpenShift

```bash
./scripts/install-openshift.sh
```

This will:
- **Validate Terraform infrastructure is complete**
- Download pull secret (or use `~/.pullsecret.json`)
- Generate SSH keypair
- Create `install-config.yaml` from Terraform outputs
- Run `openshift-install create cluster`
- Wait for installation (30-45 minutes)

The script now includes automatic validation and will **fail early** if Terraform infrastructure is incomplete.

#### 6. Install MCE 2.10

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

## Autoscaling (Optional but Recommended)

The management cluster can automatically scale workers based on hosted cluster workload. Each hosted cluster adds ~70 control plane pods to the management workers.

### Configure Autoscaling

Autoscaling is **enabled by default** but can be customized:

```hcl
# terraform.tfvars
autoscaling_enabled              = true
autoscaling_min_replicas_per_az  = 1     # Min workers per AZ
autoscaling_max_replicas_per_az  = 4     # Max workers per AZ
autoscaling_max_nodes_total      = 15    # Total worker limit

# Scale-down behavior (production defaults)
autoscaling_scale_down_delay_after_add   = "10m"
autoscaling_scale_down_unneeded_time     = "10m"
autoscaling_scale_down_utilization_threshold = 0.5  # 50%
```

### Apply Autoscaling After Cluster Creation

Autoscaling resources are applied **after** the OpenShift cluster is created:

```bash
# Ensure KUBECONFIG is set
export KUBECONFIG=~/openshift-clusters/<cluster-name>/auth/kubeconfig

# Apply autoscaling configuration
terraform apply

# Verify autoscaling is configured
oc get clusterautoscaler
oc get machineautoscaler -n openshift-machine-api
```

### Autoscaling Behavior

**Scale-Up:**
- Triggered when pods cannot be scheduled due to resource constraints
- New workers join in ~3-5 minutes
- Example: Creating 5 hosted clusters scales from 3→6 workers

**Scale-Down:**
- Triggered after 10m of low utilization (configurable)
- Workers removed in ~2-3 minutes after grace period
- Respects `minReplicas` (1 worker per AZ for HA)

**Capacity Planning:**
- **2-4 hosted clusters**: 3 workers sufficient
- **5-9 hosted clusters**: 6 workers needed
- **10-14 hosted clusters**: 9 workers needed

### Testing Autoscaling

```bash
# Create multiple hosted clusters to trigger scale-up
for i in 3 4 5; do
  ./.github/scripts/local-setup/hypershift-full-test.sh $i \
    --skip-cluster-destroy > /tmp/cluster-$i.log 2>&1 &
done

# Monitor autoscaler
oc logs -n openshift-machine-api deployment/cluster-autoscaler-default -f

# Watch workers scaling
watch -n 5 'oc get nodes -l node-role.kubernetes.io/worker'

# Destroy clusters to trigger scale-down
for i in 3 4 5; do
  ./.github/scripts/hypershift/destroy-cluster.sh $i &
done
```

See [AUTOSCALING-TUTORIAL.md](../../AUTOSCALING-TUTORIAL.md) for detailed testing guide.

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

### Installation Script Reports "Terraform state appears incomplete"

**Symptoms:**
```
✗ Terraform state appears incomplete!
✗ Found 8 resources, expected at least 20
```

**Cause:** Terraform apply did not complete successfully. This typically happens if:
- Terraform was interrupted (Ctrl+C, connection lost)
- AWS API errors during resource creation
- Missing AWS permissions

**Fix:**
```bash
cd terraform/management-cluster
terraform workspace select <cluster-name>

# Review what's missing
terraform plan -var-file=terraform-<cluster-name>.tfvars

# Complete the deployment
terraform apply -var-file=terraform-<cluster-name>.tfvars

# Verify completion
terraform state list | grep -E "(nat_gateway|eip\.nat|route_table)"
# Should show: 3 NAT gateways, 3 EIPs, 4 route tables
```

### Cluster Has No Internet Connectivity (Workers Can't Pull Images)

**Symptoms:**
- Pods stuck in `ImagePullBackOff` or `ErrImagePull`
- `dial tcp: i/o timeout` errors when pulling from quay.io, registry.redhat.io
- Load balancer health checks failing
- Authentication operator degraded

**Cause:** Missing NAT gateways - worker nodes in private subnets cannot reach the internet.

**Diagnosis:**
```bash
# Check if NAT gateways exist
aws ec2 describe-nat-gateways --region us-east-1 \
  --filter "Name=vpc-id,Values=<vpc-id>" \
  --query 'NatGateways[*].[NatGatewayId,State]'

# Should show 3 NAT gateways in "available" state
# If empty or shows "deleted", NAT gateways are missing
```

**Fix:**
Either:
1. **Recommended:** Destroy and recreate with complete Terraform apply:
   ```bash
   openshift-install destroy cluster --dir ~/openshift-clusters/<name>
   terraform destroy -var-file=terraform-<name>.tfvars
   # Then redeploy using scripts/deploy-full.sh
   ```

2. **Manual fix (if cluster must be preserved):**
   ```bash
   # Create NAT gateways manually and import to Terraform
   # See: docs/troubleshooting/missing-nat-gateways.md
   ```

### OpenShift Installation Fails

Check logs:
```bash
tail -f ~/openshift-clusters/<cluster-name>/.openshift_install.log
```

Common issues:
- Route53 hosted zone not found → create hosted zone for base domain
- AWS quota limits → request quota increase
- Subnet CIDR conflicts → adjust `vpc_cidr` in tfvars
- **Missing infrastructure** → verify terraform apply completed (see above)

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
