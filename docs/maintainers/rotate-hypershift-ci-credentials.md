# Rotating HyperShift CI Credentials

This guide explains how to rotate HyperShift CI credentials when migrating to a new management cluster or when credentials need to be refreshed.

## Overview

The rotation process:
1. Generates new AWS IAM users/keys with scoped permissions
2. Creates a new Kubernetes service account on the management cluster
3. Extracts the management cluster kubeconfig
4. Tests the credentials locally
5. Pushes all secrets to GitHub Actions in one operation

## Prerequisites

- Logged into AWS: `aws sts get-caller-identity`
- Logged into OpenShift management cluster: `oc whoami`
- Authenticated with GitHub CLI: `gh auth status`

## Step-by-Step Process

### 1. Generate Fresh Credentials

Run the setup script with `--rotate` to delete old keys and create new ones:

```bash
MANAGED_BY_TAG=kagenti-hypershift-ci \
  ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh --rotate
```

This creates:
- AWS IAM users: `kagenti-hypershift-ci` (CI) and `kagenti-hypershift-ci-debug` (read-only)
- AWS IAM role: `kagenti-hypershift-ci-role` (for hcp CLI)
- Kubernetes service account: `kagenti-hypershift-ci` in namespace `kagenti-hypershift-ci`
- Local file: `.env.kagenti-hypershift-ci` (credentials)
- Kubeconfig: `~/.kube/kagenti-hypershift-ci-mgmt.kubeconfig`

**Output:**
```
✅ All pre-flight checks passed
✅ AWS Region: us-east-1 (auto-detected from cluster)
✅ OIDC S3 bucket: hyperocto (auto-detected from operator)
✅ Setup Complete
```

### 2. Push Secrets to GitHub

Run the script to test credentials locally and push all secrets to GitHub Actions:

```bash
./.github/scripts/hypershift/generate-gh-secrets.sh
```

This will:
- Test AWS credentials locally
- Push all 8 secrets to GitHub Actions
- Verify the secrets were set

**Output:**
```
╔════════════════════════════════════════════════════════════════╗
║     Pushing GitHub Secrets for HyperShift CI                  ║
╚════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step 1: Testing AWS credentials locally...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
    "UserId": "AIDA6NU5MYLAKXXFVDBPD",
    "Account": "991393792704",
    "Arn": "arn:aws:iam::991393792704:user/kagenti-hypershift-ci"
}

✅ AWS credentials verified successfully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step 2: Pushing secrets to GitHub...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Set Actions secret AWS_ACCESS_KEY_ID
✓ Set Actions secret AWS_SECRET_ACCESS_KEY
✓ Set Actions secret AWS_REGION
✓ Set Actions secret HCP_ROLE_NAME
✓ Set Actions secret BASE_DOMAIN
✓ Set Actions secret MANAGED_BY_TAG
✓ Set Actions secret PULL_SECRET
✓ Set Actions secret HYPERSHIFT_MGMT_KUBECONFIG_BASE64

✅ All secrets pushed to GitHub

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verification:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GitHub Secrets set:
AWS_ACCESS_KEY_ID            Updated 2026-03-24
AWS_SECRET_ACCESS_KEY        Updated 2026-03-24
AWS_REGION                   Updated 2026-03-24
BASE_DOMAIN                  Updated 2026-03-24
HCP_ROLE_NAME                Updated 2026-03-24
HYPERSHIFT_MGMT_KUBECONFIG_BASE64 Updated 2026-03-24
MANAGED_BY_TAG               Updated 2026-03-24
PULL_SECRET                  Updated 2026-03-24

╔════════════════════════════════════════════════════════════════╗
║                    Setup Complete!                             ║
╚════════════════════════════════════════════════════════════════╝
```

### 3. Test CI Workflow

Trigger a CI workflow to verify the new credentials work:

```bash
# Trigger the HyperShift E2E workflow
gh workflow run e2e-hypershift.yaml --ref main
```

Monitor the workflow:
```bash
gh run list --workflow=e2e-hypershift.yaml --limit 1
gh run watch
```

## Secrets Configured

The following GitHub Actions secrets are set:

| Secret Name | Description |
|------------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS CI user access key (full permissions) |
| `AWS_SECRET_ACCESS_KEY` | AWS CI user secret key |
| `AWS_REGION` | AWS region (us-east-1) |
| `HCP_ROLE_NAME` | IAM role name for hcp CLI |
| `BASE_DOMAIN` | Route53 public zone for cluster DNS |
| `MANAGED_BY_TAG` | Resource tagging identifier |
| `PULL_SECRET` | Red Hat pull secret for OpenShift images |
| `HYPERSHIFT_MGMT_KUBECONFIG_BASE64` | Base64-encoded kubeconfig for management cluster |

## Troubleshooting

### AWS credentials test fails

If `aws sts get-caller-identity` fails in the script:

1. Check your current AWS credentials: `aws sts get-caller-identity`
2. Verify you have permissions to create IAM users/roles
3. Re-run the setup script: `./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh --rotate`

### GitHub secrets push fails

If `gh secret set` fails:

1. Check GitHub authentication: `gh auth status`
2. Verify you have admin access to the repository
3. Re-authenticate: `gh auth login`

### CI workflow fails with new credentials

If the CI workflow fails after updating secrets:

1. Check the workflow logs: `gh run view --log`
2. Verify the AWS credentials work: `source .env.kagenti-hypershift-ci && aws sts get-caller-identity`
3. Test kubeconfig: `kubectl --kubeconfig ~/.kube/kagenti-hypershift-ci-mgmt.kubeconfig get nodes`

## Security Notes

- The `.env.kagenti-hypershift-ci` file contains sensitive credentials and is gitignored
- AWS IAM policies use tag-based scoping to limit permissions to `kagenti-hypershift-ci-*` resources
- The service account has cluster-scoped permissions for HyperShift operations
- Credentials should be rotated whenever:
  - Moving to a new management cluster
  - Suspected credential compromise
  - Periodic security rotation (quarterly recommended)

## Related Documentation

- [HyperShift Setup](../hypershift/setup.md)
- [CI Workflows](.github/workflows/README.md)
- [AWS IAM Policies](.github/scripts/hypershift/policies/README.md)
