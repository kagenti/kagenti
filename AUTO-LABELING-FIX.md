# Auto-Labeling Fix Summary

**Issue:** Auto-cleanup labels were NOT applied automatically during cluster creation
**Status:** ✅ FIXED
**Date:** 2026-03-06

## The Problem

During Phase 2 testing, we discovered that auto-cleanup labels were not being applied when creating a cluster with `ENABLE_AUTO_CLEANUP=true`.

**Root Cause:**
The labeling code ran immediately after the `ansible-playbook` command completed, but the HostedCluster CR hadn't fully propagated to Kubernetes yet. The timing was too early.

**Original Timing:** Immediately after ansible-playbook (too early)

```bash
ansible-playbook site.yml ...  # Cluster creation

# Auto-labeling code HERE (TOO EARLY!)
# HostedCluster CR not yet stable
```

## The Fix

**Moved labeling logic to run AFTER NodePool health check.**

This ensures:
1. ✅ HostedCluster CR definitely exists (NodePool check validates this)
2. ✅ Cluster is in a healthy state
3. ✅ No race condition with Ansible propagation
4. ✅ Uses `MGMT_KUBECONFIG` explicitly (correct context)

**New Timing:** After NodePool health check (correct)

```bash
# NodePool health check validates cluster exists
if [ "$NP_HEALTHY" != "true" ]; then
    exit 1
fi

# Auto-labeling code HERE (CORRECT TIMING!)
# Now runs after we KNOW the HostedCluster exists
ENABLE_AUTO_CLEANUP="${ENABLE_AUTO_CLEANUP:-false}"
if [ "$ENABLE_AUTO_CLEANUP" = "true" ]; then
    # Apply labels using MGMT_KUBECONFIG
    KUBECONFIG="$MGMT_KUBECONFIG" oc label hostedcluster "$CLUSTER_NAME" -n clusters \
        "kagenti.io/auto-cleanup=enabled" \
        "kagenti.io/ttl-hours=$TTL_HOURS" \
        "kagenti.io/cluster-type=$CLUSTER_TYPE" \
        --overwrite
fi
```

## Changes Made

### 1. Modified cluster creation script

**File:** `.github/scripts/hypershift/create-cluster.sh`
**Location:** After line 446 (after NodePool health check)
**Key improvements:**
- Uses `KUBECONFIG="$MGMT_KUBECONFIG"` explicitly
- No wait loop needed (HostedCluster guaranteed to exist)
- Pattern-based TTL assignment works correctly

### 2. Pattern-Based TTL Assignment

Clusters are labeled based on their name pattern:

| Pattern | TTL | Cluster Type | Use Case |
|---------|-----|--------------|----------|
| `*-pr-*`, `*-pr[0-9]*` | 3h | `ci-pr` | Pull request tests |
| `*-main-*`, `*-merge-*` | 6h | `ci-main` | Post-merge tests |
| `kagenti-hypershift-ci-*` | 3h | `ci-generic` | Generic CI tests |
| `kagenti-hypershift-custom-*`, `*-team-*` | 168h (1 week) | `dev` | Development clusters |
| Other | 24h | `unknown` | Fallback |

### 3. Environment Variable Override

```bash
# Override pattern-based TTL
AUTO_CLEANUP_TTL_HOURS=12 ENABLE_AUTO_CLEANUP=true \
  ./create-cluster.sh my-cluster
```

## Verification

### Test Results (2026-03-06)

**Test Cluster:** `kagenti-team-test`
**Pattern Match:** `*-team-*` → TTL=168h, type=dev

**Labels Applied:**
```json
{
  "kagenti.io/auto-cleanup": "enabled",
  "kagenti.io/cluster-type": "dev",
  "kagenti.io/ttl-hours": "168"
}
```

**Cleanup Script Detection:**
```
✓ OK: kagenti-team-test
   Age: 17m | TTL: 168h | Type: dev
```

**Stale Detection (TTL=0):**
```
⚠ STALE: kagenti-team-test
   Age: 18m | TTL: 0h | Over by: 18m
   Would delete (use --apply to execute)
```

## What Was NOT Changed

1. **Pattern matching logic** - Same as designed (PR=3h, main=6h, dev=168h)
2. **Cleanup script** - No changes needed (already had fallback for missing labels)
3. **Workflow** - No changes needed
4. **CI workflows** - Not yet updated (Phase 4)

## Labels Applied

After the fix, clusters created with `ENABLE_AUTO_CLEANUP=true` get these labels:

| Label | Example Value | Purpose |
|-------|---------------|------------|
| `kagenti.io/auto-cleanup` | `enabled` | Marks cluster for auto-cleanup |
| `kagenti.io/ttl-hours` | `3` / `6` / `168` | TTL in hours (pattern-based) |
| `kagenti.io/cluster-type` | `ci-pr` / `ci-main` / `dev` | Cluster category |

**Note:** The `created-at` label was not implemented because Kubernetes labels don't allow colons in values. The cleanup script uses `.metadata.creationTimestamp` instead.

## Testing

**Manual Test (Phase 2):**
- ✅ Labels applied automatically during cluster creation
- ✅ Pattern detection worked correctly (*-team-* → 168h)
- ✅ Cleanup script detected labeled cluster
- ✅ Stale detection worked (TTL=0 test)
- ✅ Deletion worked (--apply mode)

## Success Criteria

Fix is considered successful when:
- ✅ Labels applied automatically during cluster creation
- ✅ Labels have correct values (TTL matches pattern)
- ✅ Cleanup script detects labeled clusters
- ✅ No errors in cluster creation logs
- ✅ Stale detection works correctly

## Conclusion

**The auto-labeling issue is FIXED.** The labels are now applied at the correct point in the cluster creation process, after we verify the HostedCluster CR exists and is healthy.

**Phase 4 (CI Integration) can proceed.**

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `.github/scripts/hypershift/create-cluster.sh` | Added auto-labeling after NodePool check | Apply labels when ENABLE_AUTO_CLEANUP=true |
| `.github/scripts/hypershift/cleanup-stale-clusters.sh` | Created | Detect and delete stale clusters |
| `.github/workflows/cleanup-stale-hypershift-clusters.yaml` | Created | Scheduled automation |
| `.github/scripts/hypershift/test-auto-labeling-fix.sh` | Created | End-to-end validation |
| `docs/hypershift-auto-cleanup.md` | Updated | User documentation |
