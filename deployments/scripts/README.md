# Kagenti Deployment Scripts

This directory contains utility scripts for Kagenti deployment and validation.

## Available Scripts

### preflight-check.sh

**Purpose:** Validates the OpenShift environment before Kagenti installation.

**Usage:**
```bash
./deployments/scripts/preflight-check.sh
```

**What it checks:**
- ✓ Required tools (oc/kubectl, helm, jq)
- ✓ Tool versions meet minimum requirements
- ✓ Cluster connectivity
- ✓ Admin permissions
- ✓ OpenShift version compatibility
- ✓ SPIRE/ZTWIM version requirements (OCP 4.19+)
- ✓ Network configuration (OVNKubernetes detection)

**Exit codes:**
- `0` - All checks passed (safe to proceed with installation)
- `1` - One or more critical checks failed (resolve issues before installation)

**Example output:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Kagenti OpenShift Pre-flight Checks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Validating environment for Kagenti installation...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Required Tools
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ oc CLI found: v4.19.0
✓ Helm found: v3.18.0 (>= v3.18.0)
✓ jq found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cluster Connectivity
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Connected to cluster
✓ Admin permissions verified

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenShift Version Compatibility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ℹ Detected OpenShift version: 4.19.1
✓ OpenShift version >= 4.16.0 (Kagenti compatible)
✓ OpenShift version >= 4.19.0 (SPIRE/ZTWIM supported)
  → SPIRE/ZTWIM operator can be enabled

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Network Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ℹ Network type: OVNKubernetes
⚠ OVNKubernetes detected - may require routingViaHost configuration for Istio Ambient
  → See: docs/ocp/openshift-install.md#check-cluster-network-type-and-configure-for-ovn-in-ambient-mode

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pre-flight Check Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Passed:   6
Warnings: 1
Failed:   0

✓ Pre-flight checks completed successfully!
You can proceed with Kagenti installation.

Next steps:
  1. Review any warnings above
  2. Run the installer: scripts/ocp/setup-kagenti.sh
```

**When to run:**
- Before initial Kagenti installation
- After OpenShift cluster upgrades
- When troubleshooting installation issues
- To verify environment configuration

**Version Requirements:**

| Component | Minimum Version | Notes |
|-----------|----------------|-------|
| OpenShift | 4.16.0 | Base Kagenti functionality |
| OpenShift (SPIRE) | 4.19.0 | Required for SPIRE/ZTWIM operator |
| Helm | ≥3.18.0, <4 | Chart installation |
| kubectl/oc | 1.32.1 / 4.16.0 | Cluster management |

**Troubleshooting:**

If the script reports version incompatibility:

1. **For OCP < 4.19 with SPIRE enabled:**
   - Option 1: Disable SPIRE in your values file
   - Option 2: Upgrade OpenShift to 4.19+
   - Disable SPIRE manually in your values file if on OCP < 4.19

2. **For missing tools:**
   - Install required tools (helm, oc/kubectl, jq)
   - Ensure they are in your PATH

3. **For permission issues:**
   - Verify you have cluster-admin role
   - Check your kubeconfig is correctly configured

## See Also

- [OpenShift Installation Guide](../../docs/ocp/openshift-install.md)
- [Kagenti Installation Guide](../../docs/install.md)
- [Version Compatibility Matrix](../../docs/ocp/openshift-install.md#openshift-version-compatibility)
