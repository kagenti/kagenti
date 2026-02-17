# Terraform Infrastructure for Kagenti HyperShift

This directory contains Terraform configuration for deploying an OpenShift management cluster that will run HyperShift operator with MCE 2.10 for creating OpenShift 4.20.x hosted clusters.

MCE 2.10 supports OpenShift 4.19, 4.20, and 4.21. This guide focuses on **4.20.11** which is tested and verified.

**Important:** Terraform is ONLY used for the management cluster infrastructure. Hosted clusters (sandboxes) are created using the Ansible-only approach via the standard `create-cluster.sh` script.

---

## Complete Deployment Workflow

### Admin: Deploy Management Cluster

**Step 1: Check AWS Quotas**
```bash
# Verify you have sufficient AWS quotas before starting
./.github/scripts/hypershift/check-quotas.sh
# Review output and request increases if needed
```

**Step 2: Set AWS Credentials**
```bash
# Export your AWS credentials
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_REGION="us-east-1"
```

**Step 3: Configure Terraform**
```bash
cd terraform/management-cluster

# Copy and edit configuration
cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars

# Set these values:
#   cluster_name  = "kagenti-team"  # Choose your cluster name
#   base_domain   = "example.com"   # Your Route53 domain
#   ocp_version   = "4.20.11"       # OpenShift version
```

**Step 4: Deploy Infrastructure**
```bash
terraform init
terraform apply  # Review plan, then approve
```

**Step 5: Install OpenShift**
```bash
# This takes 30-45 minutes
./scripts/install-openshift.sh
```

**Step 6: Install MCE 2.10**
```bash
# Set kubeconfig to your new management cluster
export KUBECONFIG=~/openshift-clusters/kagenti-team/auth/kubeconfig

# Install MCE and HyperShift (5-10 minutes)
./scripts/install-mce.sh
```

**Step 7: Verify Installation**
```bash
oc get nodes                           # Should show 3 masters + 3 workers
oc get multiclusterengine              # Should show "Available"
oc get deployment operator -n hypershift  # Should show "1/1 Ready"
```

**Step 8 (Optional): Setup Autoscaling**
```bash
./.github/scripts/hypershift/setup-autoscaling.sh
```

### Admin: Create Team Credential Package

After the management cluster is running, create a package for your team.

**Step 1: Create .env File**

This file contains AWS credentials and the management cluster kubeconfig:

```bash
# Replace 'kagenti-team' with your cluster name
cat > .env.kagenti-team <<EOF
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_REGION="us-east-1"
export HCP_ROLE_NAME="kagenti-team-role"
export MANAGED_BY_TAG="kagenti-team"
export BASE_DOMAIN="example.com"
export HYPERSHIFT_MGMT_KUBECONFIG_BASE64="$(base64 -w 0 ~/openshift-clusters/kagenti-team/auth/kubeconfig)"
EOF
```

**Step 2: Create credentials.txt**

This file has the web console login:

```bash
cat > credentials.txt <<EOF
Management Cluster: kagenti-team.example.com
OpenShift Version: 4.20.11
MCE Version: 2.10.1

Web Console: https://console-openshift-console.apps.kagenti-team.example.com
Username: kubeadmin
Password: $(cat ~/openshift-clusters/kagenti-team/auth/kubeadmin-password)
EOF
```

**Step 3: Create README.md**

Instructions for team members:

```bash
cat > README.md <<'EOF'
# Management Cluster Access

## Setup
```bash
# Extract and source credentials
tar -xzf package.tar.gz && cd package/
ls -la  # .env file is hidden
source .env.<tag>

# Decode kubeconfig
echo "$HYPERSHIFT_MGMT_KUBECONFIG_BASE64" | base64 -d > ~/.kube/mgmt.kubeconfig
export KUBECONFIG=~/.kube/mgmt.kubeconfig
oc whoami
```

## Create Hosted Cluster
```bash
cd ~/kagenti
source /path/to/.env.<tag>
./.github/scripts/local-setup/hypershift-full-test.sh <suffix> --skip-cluster-destroy
```
EOF
```

**Step 4 (Optional): Package for Team Distribution**

If you need to distribute these credentials to other team members:

```bash
# Create package directory
mkdir -p /tmp/<cluster-name>-package
cp .env.<tag> credentials.txt README.md /tmp/<cluster-name>-package/

# Create tarball
cd /tmp
tar -czf <cluster-name>-package.tar.gz <cluster-name>-package/

```

Share the package securely with authorized team members (Slack DM, secure file share, etc).

⚠️ **Security Note:** This package contains AWS credentials and cluster access.

### Team: Create Hosted Clusters

Team members receive the credential package and follow the included README to create hosted clusters.

The package includes:
- `.env.<tag>` file with AWS credentials and management cluster kubeconfig
- `credentials.txt` with web console access
- `README.md` with detailed setup instructions

Team members source the `.env` file and use the existing kagenti scripts to create hosted clusters on the shared management cluster.

---

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
│   └── README.md         # Technical reference
└── README.md             # This file (workflow guide)
```


## Architecture

**Management Cluster** (OpenShift 4.20.11 + MCE 2.10 + HyperShift):
- Deployed via Terraform + openshift-install
- Hosts control planes for multiple hosted clusters as pods
- Shared by entire team (~$1,500/month)

**Hosted Clusters** (lightweight, per-developer):
- Control planes run as pods on management cluster
- Workers in separate AWS VPCs
- Created/destroyed in ~15 minutes
- Minimal cost (workers only)

## Documentation

- **This file** - Complete deployment workflow and team setup guide
- [management-cluster/README.md](./management-cluster/README.md) - Technical reference, troubleshooting, configuration options
- [versions.tf](./management-cluster/versions.tf) - OpenShift and MCE version compatibility matrix
- [.github/scripts/hypershift/check-quotas.sh](../.github/scripts/hypershift/check-quotas.sh) - AWS quota checking tool

## Next Steps

**For Admins:**
1. [Check AWS quotas](#admin-deploy-management-cluster) before deployment
2. [Deploy management cluster](#admin-deploy-management-cluster)
3. [Create team credential package](#admin-create-team-credential-package)
4. Distribute package to team members

**For Team Members:**
1. Receive credential package from admin
2. [Create your hosted clusters](#team-create-hosted-clusters)
3. Run E2E tests to verify installation

## Supported Versions

This Terraform configuration uses **MCE 2.10** which supports:
- Management cluster: OpenShift 4.19, 4.20, 4.21
- Hosted clusters: OpenShift 4.19, 4.20, 4.21

**Current tested version: 4.20.11** (used by kagenti-team management cluster)
