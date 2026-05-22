# Policy Templates

This directory contains policy templates for HyperShift CI credentials.
They use variable substitution (`${VAR}`) and are rendered by `setup-hypershift-ci-credentials.sh`.

## Policy Files

| File | Purpose | Used By |
|------|---------|---------|
| `ci-user-policy.json` | Scoped AWS permissions for CI automation | `kagenti-hypershift-ci` IAM user |
| `hcp-role-policy.json` | AWS permissions for `hcp` CLI operations | `kagenti-hypershift-ci-role` IAM role |
| `debug-user-policy.json` | Read-only AWS access for debugging | `kagenti-hypershift-ci-debug` IAM user |
| `k8s-ci-clusterrole.yaml` | Kubernetes RBAC for HyperShift operations | `kagenti-hypershift-ci` ServiceAccount |

## Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `MANAGED_BY_TAG` | Primary identifier for resource scoping | `kagenti-hypershift-ci` |
| `ROUTE53_ZONE_ID` | Route53 hosted zone ID for base domain | `Z1234567890ABC` |
| `CLUSTER_ROLE_NAME` | Kubernetes ClusterRole name | `kagenti-hypershift-ci-k8s-role` |
| `CLUSTER_ROLE_BINDING_NAME` | Kubernetes ClusterRoleBinding name | `kagenti-hypershift-ci-k8s-binding` |
| `SA_NAME` | Kubernetes ServiceAccount name | `kagenti-hypershift-ci` |
| `SA_NAMESPACE` | Kubernetes namespace for ServiceAccount | `kagenti-hypershift-ci` |

## Tagging Strategy

We use a **namespaced custom tag** passed via HyperShift's `--additional-tags`:

```
Tag Key:   kagenti.io/managed-by
Tag Value: ${MANAGED_BY_TAG}  (e.g., "kagenti-hypershift-ci")

IAM policy matches with: ec2:ResourceTag/kagenti.io/managed-by
Condition: StringEquals to "${MANAGED_BY_TAG}"

This scopes ALL mutate/delete operations to only resources tagged with:
  kagenti.io/managed-by=kagenti-hypershift-ci
```

### Why This Approach?

1. **Namespaced tag key** - `kagenti.io/` prefix avoids conflicts with other tools (follows K8s label conventions)
2. **Tag-based scoping** - Destructive operations (delete, terminate) require the tag
3. **HyperShift integration** - Tags are passed via `--additional-tags` in `create-cluster.sh`
4. **VPC setup exception** - Route table operations don't require tags (AWS auto-creates main route table untagged)

### Known Limitations

**VPC Setup Operations (EC2SetupVPC section):**
- AWS auto-creates resources like the main route table without inheriting tags
- Operations like `ec2:ReplaceRouteTableAssociation` must be allowed without tag conditions
- This is a known gap - these operations are allowed on any resource

**CREATE Operations:**
- Currently allowed without requiring tags (HyperShift may create-then-tag)
- Future improvement: Add `aws:RequestTag` condition once verified HyperShift tags at creation time

## Security Model

### Resource Scoping by Type

| Resource | Scoping Method | Notes |
|----------|----------------|-------|
| **S3 Buckets** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **IAM Roles** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **IAM Profiles** | ARN prefix: `${MANAGED_BY_TAG}-*` | HARD LIMIT |
| **EC2 (mutate/delete)** | Tag: `kagenti.io/managed-by=${MANAGED_BY_TAG}` | Requires custom tag |
| **EC2 (VPC setup)** | Unrestricted | AWS auto-creates untagged resources |
| **ELB (mutate/delete)** | Tag: `kagenti.io/managed-by=${MANAGED_BY_TAG}` | Requires custom tag |
| **Route53** | Broad access | Private zones created dynamically |
| **OIDC** | Broad (ARN patterns vary) | hcp CLI only manages its own |

### IAM Condition Pattern for EC2/ELB

```json
{
  "Condition": {
    "StringEquals": {
      "ec2:ResourceTag/kagenti.io/managed-by": "${MANAGED_BY_TAG}"
    }
  }
}
```

This condition:
- Uses `StringEquals` for exact match on tag **value**
- Only allows operations on resources tagged with `kagenti.io/managed-by=kagenti-hypershift-ci`
- Applied to DELETE/TERMINATE operations (not CREATE, not VPC setup)

### What CAN Be Strictly Limited

1. **S3 Buckets** - Prefix scoping via ARN. Can only access `${MANAGED_BY_TAG}-*` buckets.
2. **IAM Roles/Profiles** - Prefix scoping via ARN. Can only manage `${MANAGED_BY_TAG}-*` resources.
3. **EC2/ELB Mutate/Delete** - Tag value matching. Only resources tagged with `kagenti.io/managed-by`.

### What CANNOT Be Strictly Limited

**EC2 VPC Setup Operations:**
- AWS auto-creates the main route table without tags
- `ReplaceRouteTableAssociation`, `AttachInternetGateway`, etc. must be unrestricted
- These operations are in the `EC2SetupVPC` section without conditions

**EC2 Create Operations:**
- Currently unrestricted (HyperShift may not tag at creation time)
- Could be tightened with `aws:RequestTag` once verified

**Route53:**
- HyperShift creates private hosted zones per cluster
- Zone IDs are not known in advance
- The `hcp` CLI only modifies records for its own cluster

**OIDC Providers:**
- OIDC provider ARN patterns vary based on bucket URL structure
- The `hcp` CLI only deletes the OIDC provider it created

### Defense in Depth

Multiple layers provide protection:

1. **IAM Policies** - Tag value matching for EC2/ELB delete/mutate, ARN prefix for S3/IAM
2. **Custom namespaced tag** - `kagenti.io/managed-by` avoids conflicts with other tools
3. **hcp CLI behavior** - Only targets resources tagged with its infra-id
4. **Cluster naming convention** - All clusters prefixed with `${MANAGED_BY_TAG}`
5. **K8s RBAC** - Limits HostedCluster management on management cluster
6. **Separate users** - CI user vs HCP role separation

## Kubernetes RBAC (k8s-ci-clusterrole.yaml)

The `k8s-ci-clusterrole.yaml` defines RBAC for the CI service account on the HyperShift management cluster.

### Why Cluster-Scoped?

Unlike AWS IAM, Kubernetes RBAC does not support namespace prefix patterns. HyperShift dynamically creates control plane namespaces (e.g., `clusters-<name>`) that CI needs to access. Since namespace names aren't known in advance and the HyperShift operator creates them, we cannot use namespace-scoped RoleBindings.

### Permission Categories

| Resource | Verbs | Purpose |
|----------|-------|---------|
| `hostedclusters`, `nodepools`, `hostedcontrolplanes` | full CRUD | Cluster lifecycle management |
| `secrets`, `configmaps`, `namespaces` | full CRUD | Cluster configuration and kubeconfig access |
| `cluster.x-k8s.io` resources | get, list, watch, **patch** | CAPI status and orphan cleanup |
| `apps/deployments`, `statefulsets` | get, list, watch, **patch** | Control plane debugging and orphan cleanup |
| `pods`, `nodes`, `events`, `pods/log` | read-only | Debugging |

### The `patch` Permission

The `patch` verb on `cluster.x-k8s.io/clusters` and `apps/deployments` is critical for cleanup:

**Problem**: When a HyperShift cluster is deleted, the control plane namespace (containing cluster-api controllers) is deleted first. This creates a deadlock:
- `Cluster` resources have finalizers requiring cluster-api controller
- Controller runs in the namespace being deleted
- Controller can't remove finalizers → namespace stuck in Terminating

**Solution**: CI service account can patch these resources to remove finalizers manually during cleanup.

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
