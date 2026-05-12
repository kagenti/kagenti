# HyperShift Cleanup System

Automated cleanup of stale and zombie HyperShift resources to prevent quota exhaustion.

## Overview

Two complementary workflows handle different cleanup scenarios:

### 1. **Stale Cluster Cleanup** (TTL-based)
- **Workflow**: `.github/workflows/cleanup-stale-hypershift-clusters.yaml`
- **Schedule**: Every 3 hours (at :27)
- **Targets**: Clusters with `kagenti.io/auto-cleanup=enabled` labels
- **Criteria**: Age > `kagenti.io/ttl-hours`

### 2. **Zombie Resource Cleanup** (Orphan detection)
- **Workflow**: `.github/workflows/cleanup-zombie-hypershift-resources.yaml`
- **Schedule**: Every 6 hours (at :17)
- **Targets**: Orphaned AWS resources + stuck clusters
- **Criteria**:
  - Clusters with `deletionTimestamp` but still exist (stuck finalizers)
  - Clusters older than 6 hours (normal E2E < 2 hours)
  - Clusters without CI slot leases (orphaned from failed jobs)
  - AWS resources without matching HostedClusters (VPCs, EIPs, Route53, OIDC)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     GitHub Actions Workflows                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌────────────────────┐         ┌──────────────────────┐      │
│  │ Stale Cleanup      │         │ Zombie Cleanup       │      │
│  │ (Every 3h)         │         │ (Every 6h)           │      │
│  │                    │         │                      │      │
│  │ - TTL-based        │         │ - Finalizer stuck    │      │
│  │ - Label-based      │         │ - Age-based          │      │
│  │                    │         │ - Orphan detection   │      │
│  └─────────┬──────────┘         └──────────┬───────────┘      │
│            │                               │                   │
└────────────┼───────────────────────────────┼───────────────────┘
             │                               │
             ▼                               ▼
    ┌────────────────────┐         ┌─────────────────────┐
    │ cleanup-stale-     │         │ cleanup-zombies.sh  │
    │ clusters.sh        │         │                     │
    └─────────┬──────────┘         └──────────┬──────────┘
              │                               │
              └───────────┬───────────────────┘
                          ▼
                ┌──────────────────────┐
                │ destroy-cluster.sh   │
                │ (calls ↓)            │
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────────────┐
                │ 55-cleanup-existing-cluster  │
                │                              │
                │ - Ansible playbook           │
                │ - AWS resource cleanup       │
                │ - Dependency ordering        │
                └──────────────────────────────┘
```

## Cleanup Phases

### Phase 1: HostedCluster Deletion
```bash
# For stuck clusters with deletionTimestamp
1. Check if AWS resources cleaned → force remove finalizers
2. Otherwise, initiate destroy via destroy-cluster.sh
```

### Phase 2: AWS Resource Cleanup (55-cleanup-existing-cluster.sh)
```
Dependency-ordered deletion:
1. EC2 Instances        (terminate + wait)
2. NAT Gateways         (delete + wait ~2 min)
3. Internet Gateways    (detach + delete)
4. VPC Endpoints        (delete + wait ~90s for ENI release)
5. ENIs                 (detach + delete)
6. Security Groups      (revoke rules + delete)
7. Subnets              (delete - removes route table associations)
8. Route Tables         (delete non-main)
9. VPC                  (final deletion)
```

### Phase 3: Orphan Cleanup
```
- OIDC Providers (IAM)
- Elastic IPs (unattached)
- Route53 Zones (DNS records + zone)
```

## Required GitHub Secrets

| Secret | Description | Example |
|--------|-------------|---------|
| `HYPERSHIFT_MGMT_KUBECONFIG` | Base64-encoded management cluster kubeconfig | `cat ~/.kube/config \| base64 -w0` |
| `AWS_ACCESS_KEY_ID` | AWS access key with EC2/VPC/IAM permissions | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | `...` |
| `AWS_REGION` | AWS region | `us-east-1` |
| `MANAGED_BY_TAG` | Tag prefix for clusters | `kagenti-hypershift-custom` |
| `HCP_ROLE_NAME` | HyperShift IAM role name | `kagenti-hcp-role` |

## Configuration

### Enable Automatic Stale Cleanup

Edit `.github/workflows/cleanup-stale-hypershift-clusters.yaml`:

```yaml
# Change from:
bash ./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run --verbose

# To:
bash ./.github/scripts/hypershift/cleanup-stale-clusters.sh --apply --verbose
```

### Enable Automatic Zombie Cleanup

Zombie cleanup is **enabled by default** in scheduled mode (`--force`).

To disable, change in `.github/workflows/cleanup-zombie-hypershift-resources.yaml`:

```yaml
# Change from:
bash ./.github/scripts/hypershift/cleanup-zombies.sh --force

# To:
bash ./.github/scripts/hypershift/cleanup-zombies.sh  # dry-run
```

### Adjust Zombie Age Threshold

Default: 6 hours (normal E2E runs < 2 hours)

To change globally:

```yaml
# In cleanup-zombie-hypershift-resources.yaml
env:
  MAX_CLUSTER_AGE_HOURS: 8  # Change to 8 hours
```

## Manual Triggers

### Via GitHub UI

1. Go to **Actions** → **Workflows**
2. Select workflow:
   - "Cleanup Stale HyperShift Clusters"
   - "Cleanup Zombie HyperShift Resources"
3. Click **Run workflow**
4. Configure options:
   - **dry_run**: `true` (default) or `false`
   - **pattern**: Filter clusters (e.g., `*-pr-*`)
   - **max_age_hours**: Override default (zombie cleanup only)

### Via CLI

```bash
# Stale cleanup (dry-run)
gh workflow run cleanup-stale-hypershift-clusters.yaml

# Stale cleanup (apply)
gh workflow run cleanup-stale-hypershift-clusters.yaml \
  -f dry_run=false

# Zombie cleanup (dry-run)
gh workflow run cleanup-zombie-hypershift-resources.yaml

# Zombie cleanup (apply)
gh workflow run cleanup-zombie-hypershift-resources.yaml \
  -f dry_run=false
```

## Local Usage

### Stale Cleanup

```bash
# Setup
source .env.kagenti-hypershift-custom

# Dry-run (show what would be deleted)
./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run --verbose

# Apply (actually delete)
./.github/scripts/hypershift/cleanup-stale-clusters.sh --apply

# Filter by pattern
./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run --pattern "*-pr-*"
```

### Zombie Cleanup

```bash
# Setup
source .env.kagenti-hypershift-custom

# Dry-run
./.github/scripts/hypershift/cleanup-zombies.sh

# Apply
./.github/scripts/hypershift/cleanup-zombies.sh --force

# Specific cluster
./.github/scripts/hypershift/cleanup-zombies.sh --cluster kagenti-hypershift-custom-test1 --force

# Custom age threshold
MAX_CLUSTER_AGE_HOURS=8 ./.github/scripts/hypershift/cleanup-zombies.sh --force
```

## Monitoring

### Check Recent Runs

```bash
# Stale cleanup
gh run list --workflow=cleanup-stale-hypershift-clusters.yaml --limit 5

# Zombie cleanup
gh run list --workflow=cleanup-zombie-hypershift-resources.yaml --limit 5
```

### View Logs

```bash
# Get latest run
gh run view --workflow=cleanup-zombie-hypershift-resources.yaml --log

# Download artifacts
gh run download <run-id>
```

### Audit Trail

Cleanup workflows create GitHub issues for audit:
- Label: `automated-cleanup`
- Contains: timestamp, deleted clusters, workflow run link
- Logs: Available as workflow artifacts (90-day retention)

## Quota Check

Before cleanup:

```bash
source .env.kagenti-hypershift-custom
./.github/scripts/hypershift/check-quotas.sh
```

## Safety Features

- **Dry-run by default**: Must explicitly enable `--apply` or `--force`
- **Protected clusters**: Never deletes `kagenti.io/protected=true`
- **Dependency ordering**: Respects AWS resource dependencies
- **Verification**: Checks AWS resources before removing finalizers
- **Retry logic**: Waits for NAT gateways, VPC endpoints to fully delete
- **Audit trail**: Creates GitHub issues with deletion summary
- **Logs**: Uploaded as artifacts (90-day retention)

## Troubleshooting

### "AWS resources still exist" Error

```bash
# Debug what resources remain
./.github/scripts/hypershift/debug-aws-hypershift.sh <cluster-name>

# Force cleanup
./.github/scripts/hypershift/ci/55-cleanup-existing-cluster.sh
```

### Stuck Finalizers

```bash
# Check if safe to remove
./.github/scripts/hypershift/debug-aws-hypershift.sh --check <cluster-name>

# If clean, manually patch
oc patch hostedcluster -n clusters <cluster-name> \
  -p '{"metadata":{"finalizers":null}}' --type=merge
```

### VPC Won't Delete

Common blockers:
1. NAT Gateways still deleting (wait 2-3 min)
2. VPC Endpoint ENIs not released (wait ~90s)
3. EC2 instances still terminating

## Related Documentation

- [HyperShift Cluster Creation](./create-cluster.sh)
- [Quota Check](./check-quotas.sh)
- [AWS Debug](./debug-aws-hypershift.sh)
- [CI Slot Management](./ci/slots/README.md)
