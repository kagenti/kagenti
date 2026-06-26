# MCE Upgrade Guide - Preserving HyperShift OIDC Configuration

## Background

MCE (MultiCluster Engine) manages the HyperShift operator. During MCE upgrades, the HyperShift operator deployment can lose its OIDC S3 configuration, breaking AWS cluster creation.

**Tracked issue**: OCPBUGS-XXXXX (add bug number when created)

## Current State

✅ **MCE updates are set to Manual** to prevent silent breakage  
✅ **Upgrade wrapper script** available to safely upgrade while preserving OIDC config

## How to Upgrade MCE

### Option 1: Use the Wrapper Script (Recommended)

The wrapper script automatically backs up OIDC config, upgrades MCE, and restores the config.

```bash
# Run the upgrade wrapper
./.github/scripts/hypershift/mce-upgrade-wrapper.sh

# The script will:
# 1. Backup current OIDC configuration
# 2. Detect pending MCE upgrades
# 3. Prompt for confirmation
# 4. Approve and monitor the upgrade
# 5. Restore OIDC configuration
# 6. Verify everything works
```

### Option 2: Manual Upgrade

If you prefer to upgrade manually:

```bash
# 1. Backup OIDC configuration
oc get deployment operator -n hypershift -o json | \
  jq -r '.spec.template.spec.containers[0].args[] | select(contains("oidc"))' > /tmp/oidc-backup.txt

# 2. Check for pending upgrades
oc get installplan -n multicluster-engine

# 3. Approve the upgrade
oc patch installplan <install-plan-name> -n multicluster-engine \
  --type merge -p '{"spec":{"approved":true}}'

# 4. Wait for completion
oc get subscription multicluster-engine -n multicluster-engine -w

# 5. Restore OIDC configuration
cat > /tmp/oidc-patch.json <<EOF
[
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-bucket-name=hyperocto"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-region=us-east-1"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-credentials=/etc/oidc-storage-provider-s3-creds/credentials"}
]
EOF

oc patch deployment operator -n hypershift --type=json --patch-file=/tmp/oidc-patch.json

# 6. Verify
./.github/scripts/hypershift/preflight-check.sh
```

## Checking for Available Upgrades

```bash
# Check current MCE version
oc get subscription multicluster-engine -n multicluster-engine \
  -o jsonpath='{.status.currentCSV}'

# Check for pending upgrades
oc get installplan -n multicluster-engine

# If upgrades are available, you'll see installplans with approved=false
oc get installplan -n multicluster-engine -o json | \
  jq -r '.items[] | select(.spec.approved == false) | "\(.metadata.name): \(.spec.clusterServiceVersionNames[])"'
```

## Switching Back to Automatic Updates

⚠️ **Not recommended until bug is fixed**, but if needed:

```bash
oc patch subscription multicluster-engine -n multicluster-engine \
  --type merge -p '{"spec":{"installPlanApproval":"Automatic"}}'
```

## Verifying OIDC Configuration

After any upgrade, verify OIDC is configured:

```bash
# Quick check
oc get deployment operator -n hypershift -o jsonpath='{.spec.template.spec.containers[0].args}' | \
  grep oidc

# Full preflight check
./.github/scripts/hypershift/preflight-check.sh

# Expected output:
# ✓ HyperShift operator has OIDC S3 configured (bucket: hyperocto)
```

## Emergency Recovery

If OIDC config is lost and CI is failing:

```bash
# Quick fix using preflight script
./.github/scripts/hypershift/preflight-check.sh --auto-fix

# Or manual patch
cat > /tmp/oidc-patch.json <<EOF
[
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-bucket-name=hyperocto"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-region=us-east-1"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--oidc-storage-provider-s3-credentials=/etc/oidc-storage-provider-s3-creds/credentials"}
]
EOF

oc patch deployment operator -n hypershift --type=json --patch-file=/tmp/oidc-patch.json
```

## Troubleshooting

### Upgrade Stuck

```bash
# Check install plan status
oc get installplan -n multicluster-engine

# Check MCE operator logs
oc logs -n multicluster-engine -l name=multicluster-engine --tail=100

# Check HyperShift operator status
oc get deployment operator -n hypershift
oc logs -n hypershift -l name=operator --tail=100
```

### OIDC Config Not Restored

```bash
# Verify secret and configmap exist
oc get secret hypershift-operator-oidc-provider-s3-credentials -n hypershift
oc get configmap oidc-storage-provider-s3-config -n kube-public

# Check operator deployment
oc get deployment operator -n hypershift -o yaml | grep -A 5 oidc

# Manually re-apply if needed
./.github/scripts/hypershift/preflight-check.sh --auto-fix
```

## Contact

- **Issue tracking**: OCPBUGS-XXXXX
- **Kagenti team**: Ryan Jenkins, Ladas
- **Date**: June 10, 2026
