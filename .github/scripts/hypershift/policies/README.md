# IAM Policy Templates

These policy templates define the AWS IAM permissions for HyperShift CI operations.
They use variable substitution (`${VAR}`) and are rendered by `setup-hypershift-ci-credentials.sh`.

## Policy Files

| File | Purpose | Used By |
|------|---------|---------|
| `ci-user-policy.json` | Scoped permissions for CI automation | `kagenti-hypershift-ci` IAM user |
| `hcp-role-policy.json` | Permissions for `hcp` CLI operations | `kagenti-hypershift-ci-role` IAM role |
| `debug-user-policy.json` | Read-only access for debugging | `kagenti-hypershift-ci-debug` IAM user |

## Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `MANAGED_BY_TAG` | Primary identifier for resource scoping | `kagenti-hypershift-ci` |
| `ROUTE53_ZONE_ID` | Route53 hosted zone ID for base domain | `Z1234567890ABC` |

## Tagging Strategy

We use **HyperShift's built-in tagging** rather than a custom `ManagedBy` tag:

```
HyperShift tags all resources with: kubernetes.io/cluster/<cluster-name>=owned

IAM policy matches with: ForAnyValue:StringLike on aws:TagKeys
Pattern: kubernetes.io/cluster/${MANAGED_BY_TAG}-*

This matches clusters like:
- kagenti-hypershift-ci-local    -> kubernetes.io/cluster/kagenti-hypershift-ci-local=owned
- kagenti-hypershift-ci-123      -> kubernetes.io/cluster/kagenti-hypershift-ci-123=owned
- kagenti-hypershift-ci-pr-456   -> kubernetes.io/cluster/kagenti-hypershift-ci-pr-456=owned
```

### Why This Approach?

1. **No fork needed** - Uses upstream hypershift-automation without `--additional-tags`
2. **Already enforced** - HyperShift always creates this tag on all resources
3. **Multi-cluster support** - Prefix pattern matches all our clusters
4. **Simpler** - No need to pass custom tags through the pipeline

## Security Model

### Resource Scoping by Type

| Resource | Scoping Method | Notes |
|----------|----------------|-------|
| **S3 Buckets** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **IAM Roles** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **IAM Profiles** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **EC2** | Tag key pattern: `kubernetes.io/cluster/${MANAGED_BY_TAG}-*` | Matches HyperShift tag |
| **ELB** | Tag key pattern: `kubernetes.io/cluster/${MANAGED_BY_TAG}-*` | Matches HyperShift tag |
| **Route53** | Zone ID (CI user) / All zones (HCP role) | Private zones created dynamically |
| **OIDC** | Broad (ARN patterns vary) | hcp CLI only manages its own |

### IAM Condition Pattern

```json
{
  "Condition": {
    "ForAnyValue:StringLike": {
      "aws:TagKeys": "kubernetes.io/cluster/${MANAGED_BY_TAG}-*"
    }
  }
}
```

This condition:
- Uses `ForAnyValue:StringLike` for pattern matching on tag **keys**
- Matches any resource tagged with `kubernetes.io/cluster/kagenti-hypershift-ci-*`
- Works for both creation and deletion operations

### What CAN Be Strictly Limited

1. **S3 Buckets** - Prefix scoping via ARN. Can only access `${MANAGED_BY_TAG}-*` buckets.
2. **IAM Roles/Profiles** - Prefix scoping via ARN. Can only manage `${MANAGED_BY_TAG}-*` resources.
3. **EC2/ELB** - Tag key pattern matching. Only resources tagged with matching cluster name.

### What CANNOT Be Strictly Limited

**Route53:**
- HyperShift creates private hosted zones per cluster
- Zone IDs are not known in advance
- The `hcp` CLI only modifies records for its own cluster

**OIDC Providers:**
- OIDC provider ARN patterns vary based on bucket URL structure
- The `hcp` CLI only deletes the OIDC provider it created

### Defense in Depth

Multiple layers provide protection:

1. **IAM Policies** - Tag key pattern matching for EC2/ELB, ARN prefix for S3/IAM
2. **hcp CLI behavior** - Only targets resources tagged with its infra-id
3. **Cluster naming convention** - All clusters prefixed with `${MANAGED_BY_TAG}`
4. **K8s RBAC** - Limits HostedCluster management on management cluster
5. **Separate users** - CI user vs HCP role separation

## Testing Policy Changes

Before applying policy changes in production:

1. **Validate JSON syntax:**
   ```bash
   for f in policies/*.json; do jq . "$f" > /dev/null && echo "$f: OK"; done
   ```

2. **Render with variables:**
   ```bash
   export MANAGED_BY_TAG=kagenti-hypershift-ci
   export ROUTE53_ZONE_ID=Z1234567890ABC
   envsubst < policies/hcp-role-policy.json | jq .
   ```

3. **Test in AWS Policy Simulator:**
   - Go to IAM -> Policy Simulator
   - Test specific actions against the policy

## Updating Policies

1. Edit the policy JSON files in this directory
2. Run `setup-hypershift-ci-credentials.sh` to apply changes
3. Existing IAM policy versions will be updated (old versions are deleted to make room)
