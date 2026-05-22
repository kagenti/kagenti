# HyperShift Cluster Auto-Cleanup

Automated cleanup of stale HyperShift clusters based on time-to-live (TTL) labels.

## Overview

The auto-cleanup feature helps manage HyperShift cluster lifecycle by automatically marking clusters for deletion after a configurable TTL expires. This prevents forgotten clusters from accumulating AWS costs and helps maintain a clean testing environment.

## How It Works

1. **Opt-in**: Set `ENABLE_AUTO_CLEANUP=true` when creating a cluster
2. **Pattern-based TTL**: TTL is automatically determined by cluster name pattern
3. **Label-based tracking**: Cluster metadata is stored as Kubernetes labels
4. **Protection mechanisms**: Clusters can be protected from auto-deletion
5. **Scheduled cleanup**: GitHub Actions workflow checks for stale clusters periodically

## TTL Defaults (Pattern-Based)

| Cluster Name Pattern | TTL | Use Case | Example |
|---------------------|-----|----------|---------|
| `*-pr-*` or `*-pr[0-9]*` | 3 hours | PR test clusters | `kagenti-hypershift-ci-pr529` |
| `*-main-*` or `*-merge-*` | 6 hours | Post-merge test clusters | `kagenti-hypershift-ci-main-test` |
| `kagenti-hypershift-ci-*` | 3 hours | Generic CI clusters | `kagenti-hypershift-ci-test123` |
| `kagenti-hypershift-custom-*` | 168 hours (1 week) | Developer clusters | `kagenti-hypershift-custom-ladas` |
| `*-team-*` | 168 hours (1 week) | Team shared clusters | `kagenti-team-demo` |
| _Unknown pattern_ | 24 hours | Safety default | `my-custom-cluster` |

## Labels Applied

When auto-cleanup is enabled, the following labels are added to the `HostedCluster` resource:

```yaml
metadata:
  labels:
    kagenti.io/auto-cleanup: "enabled"          # Marks cluster for auto-cleanup
    kagenti.io/ttl-hours: "3"                   # TTL in hours (pattern-based)
    kagenti.io/cluster-type: "ci-pr"            # Cluster type for categorization
    kagenti.io/created-at: "2026-03-05T10:30:00Z"  # ISO 8601 creation timestamp
```

## Usage

### Create Cluster with Auto-Cleanup

```bash
# Enable auto-cleanup (uses pattern-based TTL)
ENABLE_AUTO_CLEANUP=true ./.github/scripts/hypershift/create-cluster.sh pr529

# Enable with custom TTL override (12 hours instead of pattern default)
ENABLE_AUTO_CLEANUP=true AUTO_CLEANUP_TTL_HOURS=12 \
  ./.github/scripts/hypershift/create-cluster.sh pr529
```

### Create Cluster WITHOUT Auto-Cleanup (Default)

```bash
# Auto-cleanup is disabled by default
./.github/scripts/hypershift/create-cluster.sh pr529
```

### Protect Cluster from Auto-Deletion

Add the `protected` label to prevent a cluster from being auto-deleted:

```bash
# Protect a cluster (even if TTL expires)
oc label hostedcluster kagenti-hypershift-ci-pr529 -n clusters \
  kagenti.io/protected=true

# Remove protection
oc label hostedcluster kagenti-hypershift-ci-pr529 -n clusters \
  kagenti.io/protected-
```

### Extend TTL Temporarily

```bash
# Extend TTL to 48 hours for an existing cluster
oc label hostedcluster kagenti-hypershift-ci-pr529 -n clusters \
  kagenti.io/ttl-hours=48 --overwrite
```

### Check Cluster Auto-Cleanup Status

```bash
# View auto-cleanup labels for all clusters
oc get hostedclusters -n clusters \
  -o custom-columns=NAME:.metadata.name,AUTO_CLEANUP:.metadata.labels.'kagenti\.io/auto-cleanup',TTL:.metadata.labels.'kagenti\.io/ttl-hours',TYPE:.metadata.labels.'kagenti\.io/cluster-type',CREATED:.metadata.labels.'kagenti\.io/created-at'

# Check specific cluster
oc get hostedcluster kagenti-hypershift-ci-pr529 -n clusters \
  -o jsonpath='{.metadata.labels}'
```

## Manual Cleanup

The cleanup script identifies and deletes stale clusters based on their TTL:

```bash
# Dry run (show what would be deleted) - default mode
./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run

# Apply cleanup (actually delete stale clusters)
./.github/scripts/hypershift/cleanup-stale-clusters.sh --apply

# Cleanup specific pattern only
./.github/scripts/hypershift/cleanup-stale-clusters.sh --apply --pattern "kagenti-hypershift-ci-*"

# Verbose output (shows all clusters, not just stale)
./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run --verbose
```

### How It Works

1. Fetches all `HostedCluster` resources with label `kagenti.io/auto-cleanup=enabled`
2. For each cluster:
   - Checks if `kagenti.io/protected=true` (skip if protected)
   - Calculates age from `kagenti.io/created-at` label
   - Compares age against `kagenti.io/ttl-hours` label
   - If age > TTL: marks as stale
3. In `--apply` mode: calls `destroy-cluster.sh` for each stale cluster
4. Logs all deletions to `/tmp/cleanup-delete-<cluster-name>-<timestamp>.log`

### Example Output

```bash
$ ./.github/scripts/hypershift/cleanup-stale-clusters.sh --dry-run --verbose

╔════════════════════════════════════════════════════════════════╗
║       Cleanup Stale HyperShift Clusters                        ║
╚════════════════════════════════════════════════════════════════╝

Mode: DRY RUN (no changes)
Pattern: all clusters

→ Fetching clusters with auto-cleanup enabled...
✓ Found 3 cluster(s) with auto-cleanup enabled

⚠ STALE: kagenti-hypershift-ci-pr529
       Age: 5h 23m | TTL: 3h | Over by: 2h 23m | Type: ci-pr
       Would delete (use --apply to execute)

→ PROTECTED: kagenti-hypershift-custom-demo (kagenti.io/protected=true)

  OK: kagenti-hypershift-ci-test123 (age: 1h 15m, remaining: 1h 45m, TTL: 3h)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Summary:
  - Total checked: 3
  - Stale: 1 (would delete)
  - Protected: 1
  - Not stale: 1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

→ Run with --apply to delete stale clusters
```

## Scheduled Cleanup (Future - Phase 3)

A GitHub Actions workflow will run periodically to clean up stale clusters:

- **Schedule**: Every 3 hours (matches fastest TTL)
- **Default mode**: Dry-run (shows what would be deleted)
- **Manual trigger**: Workflow dispatch with `--apply` to actually delete
- **Audit trail**: Creates GitHub issues for deletion events

## CI Integration

### Enable for CI Workflows

Add to your GitHub Actions workflow:

```yaml
- name: Create HyperShift cluster
  env:
    ENABLE_AUTO_CLEANUP: "true"
    AUTO_CLEANUP_TTL_HOURS: "3"  # Optional override
  run: |
    bash .github/scripts/local-setup/hypershift-full-test.sh pr${{ github.event.pull_request.number }}
```

### Example: PR Testing

```yaml
# .github/workflows/e2e-hypershift-pr.yaml
env:
  CLUSTER_SUFFIX: pr${{ github.event.pull_request.number }}
  ENABLE_AUTO_CLEANUP: "true"
  # TTL will be 3h (auto-detected from *-pr-* pattern)
```

## Testing

Test the pattern matching logic without creating clusters:

```bash
./.github/scripts/hypershift/test-cleanup-patterns.sh
```

Example output:
```
╔════════════════════════════════════════════════════════════════╗
║       Auto-Cleanup Pattern Matching Test                      ║
╚════════════════════════════════════════════════════════════════╝

✓ kagenti-hypershift-ci-pr529                   → TTL: 3h, Type: ci-pr
✓ kagenti-hypershift-ci-main-test               → TTL: 6h, Type: ci-main
✓ kagenti-hypershift-custom-ladas               → TTL: 168h, Type: dev
...
```

## Safety Features

1. **Opt-in by default**: Auto-cleanup must be explicitly enabled
2. **Protection label**: `kagenti.io/protected=true` prevents deletion
3. **Pattern-based defaults**: Conservative TTL for unknown patterns (24h)
4. **Dry-run mode**: Cleanup script shows impact before applying
5. **Audit trail**: Deletion events create GitHub issues
6. **Manual override**: TTL can be extended at any time

## Troubleshooting

### Cluster was deleted unexpectedly

Check if auto-cleanup was enabled:
```bash
# Check deleted cluster's last state (if still in etcd history)
oc get hostedcluster kagenti-hypershift-ci-pr529 -n clusters \
  --ignore-not-found -o yaml | grep -A 5 "kagenti.io"
```

### Protect all existing clusters

```bash
# Add protection to all clusters
oc get hostedclusters -n clusters -o name | while read cluster; do
  oc label $cluster kagenti.io/protected=true
done
```

### Disable auto-cleanup for all future clusters

Don't set `ENABLE_AUTO_CLEANUP=true`. Auto-cleanup is **disabled by default**.

## Migration Plan

### Phase 1 (Current)
- ✅ Cluster creation script adds labels
- ✅ Pattern matching logic
- ✅ Test suite for validation

### Phase 2 (Next)
- ⏳ Cleanup script implementation
- ⏳ Manual cleanup testing

### Phase 3 (Future)
- ⏳ GitHub Actions scheduled workflow
- ⏳ Audit trail and notifications
- ⏳ Enable in CI workflows

## Cost Impact

Example AWS costs saved per forgotten cluster (3 workers, m5.xlarge):

| Cluster Age | Cost |
|------------|------|
| 1 day | $13.82 |
| 1 week | $96.77 |
| 1 month | $414.72 |

Auto-cleanup with 3-hour TTL prevents >95% of forgotten cluster costs.

## References

- [HyperShift Cluster Creation](../../../.github/scripts/hypershift/create-cluster.sh)
- [Pattern Test Suite](../../../.github/scripts/hypershift/test-cleanup-patterns.sh)
- [HyperShift Development Guide](developer/hypershift.md)
