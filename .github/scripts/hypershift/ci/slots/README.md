# CI Slot Management

This directory contains scripts for managing parallel CI runs using Kubernetes Lease-based slot locking.

## Overview

HyperShift clusters are expensive (real AWS infrastructure). To prevent resource exhaustion and enable controlled parallelism, we use a slot-based system:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CI Job Starts                                   │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  1. acquire.sh - Try to CREATE Lease (atomic, fails if exists)           │
│     - Name: kagenti-ci-slot-<N> where N ∈ [0, MAX_SLOTS-1]               │
│     - If created → slot acquired                                          │
│     - If all exist → wait and retry, cleanup expired leases               │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  2. check-capacity.sh - Verify management cluster has resources          │
│     - Checks CPU/memory including autoscaling headroom                    │
│     - Prevents half-deployed clusters stuck on scheduling                 │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  3. Create cluster, deploy Kagenti, run E2E tests                        │
│     - ResourceQuota provides final safety net                             │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  4. release.sh - DELETE Lease (always runs via exit trap/if:always)      │
│     - Ensures slot is freed even on failure/cancellation                  │
└──────────────────────────────────────────────────────────────────────────┘
```

## Scripts

| Script | Purpose |
|--------|---------|
| `acquire.sh` | Acquire a slot (creates Lease atomically) |
| `release.sh` | Release a slot (deletes Lease) |
| `check-capacity.sh` | Verify cluster has resources for new cluster |
| `cleanup-stale.sh` | Clean up expired leases and orphaned clusters |
| `status.sh` | Show current slot status |

## Resources

| File | Purpose |
|------|---------|
| `resources/resourcequota.yaml` | Hard limit on HostedCluster count (safety net) |

**Note**: RBAC for Lease management is included in the main CI ClusterRole
(`policies/k8s-ci-clusterrole.yaml`), applied by `setup-hypershift-ci-credentials.sh`.

## Usage

### Check Current Status
```bash
source .env.hypershift-ci
./.github/scripts/hypershift/ci/slots/status.sh

# Watch mode (refreshes every 10s)
./.github/scripts/hypershift/ci/slots/status.sh --watch
```

### Manual Slot Operations
```bash
# Acquire a slot (for testing)
MAX_SLOTS=2 CLUSTER_SUFFIX=test ./.github/scripts/hypershift/ci/slots/acquire.sh

# Release a slot
./.github/scripts/hypershift/ci/slots/release.sh 0

# Cleanup stale slots
./.github/scripts/hypershift/ci/slots/cleanup-stale.sh
```

### Deploy ResourceQuota (Admin)
```bash
# Apply ResourceQuota (requires admin, one-time setup)
oc apply -f ./.github/scripts/hypershift/ci/slots/resources/resourcequota.yaml

# Verify
oc get resourcequota -n clusters
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_SLOTS` | `2` | Maximum parallel CI runs |
| `SLOT_TIMEOUT` | `60` | Minutes to wait for slot |
| `LEASE_DURATION_SECONDS` | `7200` | Lease TTL (2 hours) |
| `NAMESPACE` | `clusters` | Namespace for Leases |
| `LEASE_PREFIX` | `kagenti-ci-slot` | Prefix for Lease names |

## Why Kubernetes Leases?

1. **Atomic creation** - Creating a Lease that already exists fails atomically (no race conditions)
2. **Built-in semantics** - `holderIdentity`, `acquireTime`, `leaseDurationSeconds`
3. **No external dependencies** - Native Kubernetes API
4. **Used by K8s itself** - Same mechanism for leader election

## Safety Layers

1. **Lease-based locking** - Coordinates CI runs, provides waiting/queuing
2. **Capacity check** - Ensures resources available before starting
3. **ResourceQuota** - Hard limit prevents runaway cluster creation
4. **Lease TTL** - Auto-expires stale locks after 2 hours

## Troubleshooting

### All slots occupied
```bash
# Check who holds slots
./.github/scripts/hypershift/ci/slots/status.sh

# Clean up expired slots
./.github/scripts/hypershift/ci/slots/cleanup-stale.sh
```

### Orphaned cluster (cluster exists but no lease)
```bash
# Cleanup will detect this
./.github/scripts/hypershift/ci/slots/cleanup-stale.sh

# Manual destroy
./.github/scripts/hypershift/destroy-cluster.sh <suffix>
```

### Capacity check fails
```bash
# Check current capacity
./.github/scripts/hypershift/ci/slots/check-capacity.sh

# View cluster resource usage
oc adm top nodes
```
