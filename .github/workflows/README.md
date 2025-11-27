# Snyk Security Scanning Workflow

## Overview

This workflow provides comprehensive security scanning for the Kagenti project using Snyk.

## What Gets Scanned

### 1. Python Dependencies (`snyk-python`)
- **Files**: All `pyproject.toml`, `requirements.txt`, `Pipfile`
- **Checks**: Known vulnerabilities in dependencies, license compliance
- **Action**: Blocks PRs on high-severity fixable vulnerabilities

### 2. Container Images (`snyk-docker`)
- **Images**: `kagenti/ui` Docker image
- **Checks**: Base image vulnerabilities, application dependencies in containers
- **Action**: Blocks PRs on high-severity fixable vulnerabilities

### 3. Infrastructure as Code (`snyk-iac`)
- **Files**: Kubernetes manifests, Helm charts
- **Checks**: Misconfigurations, security best practices
- **Action**: Blocks PRs on high-severity issues

### 4. Source Code (`snyk-code`)
- **Language**: Python
- **Checks**: Security vulnerabilities in source code (SAST)
- **Action**: Blocks PRs on high-severity issues

### 5. License Compliance (`snyk-license-compliance`)
- **Scope**: All Python dependencies
- **Checks**: License policy violations
- **Action**: Informational only (runs on main branch and scheduled scans)

## Triggers

- **Pull Requests**: Runs on all PRs to `main` branch (blocking mode)
- **Push to Main**: Runs and uploads results to Snyk platform for monitoring
- **Scheduled**: Weekly on Monday at 2am UTC
- **Manual**: Can be triggered via workflow_dispatch

## Required Secrets

### `SNYK_TOKEN`
- **Required**: Yes
- **Where to get it**:
  1. Create/login to account at https://snyk.io
  2. Go to Account Settings → General → Auth Token
  3. Or run `snyk config get api` from Snyk CLI
- **How to add**:
  1. Repository Settings → Secrets and variables → Actions
  2. New repository secret: `SNYK_TOKEN`

### `SNYK_ORG_ID` (Optional)
- **Required**: No (but recommended for monitoring)
- **Where to get it**:
  1. Snyk dashboard → Settings → Organization ID
- **Purpose**: Links scan results to your Snyk organization for tracking

## Behavior by Event Type

| Event | Python | Docker | IaC | Code | License | Upload to Snyk |
|-------|--------|--------|-----|------|---------|----------------|
| **PR** | Block on high | Block on high | Block on high | Block on high | ❌ Skip | No |
| **Push to main** | Monitor | Monitor | Monitor | Monitor | ✅ Check | Yes |
| **Scheduled** | Monitor | Monitor | Monitor | Monitor | ✅ Check | Yes |

## Severity Thresholds

All scans use `--severity-threshold=high`, meaning:
- ✅ **Critical & High**: Reported and can block builds
- ⚠️ **Medium & Low**: Not reported (reducing noise)

## Fail-On Strategy

Uses `--fail-on=upgradable` for dependency scans, meaning:
- ✅ Fails if a fix is available (actionable)
- ⚠️ Passes if no fix exists (avoids blocking on unfixable issues)

## GitHub Security Integration

All scans upload SARIF reports to GitHub's Security tab with unique categories:
- `python-dependencies`
- `container-image`
- `infrastructure-as-code`
- `sast`

**Note**: Private repositories require GitHub Advanced Security license.

## Excluding False Positives

### For Dependencies (Python, Docker)
Edit `.snyk` file at repository root:

```yaml
ignore:
  'SNYK-PYTHON-REQUESTS-1234567':
    - '*':
        reason: 'False positive - not applicable'
        expires: '2025-12-31T00:00:00.000Z'
```

### For Code (SAST)
Already configured in `.snyk`:

```yaml
exclude:
  code:
    - tests/
    - docs/
    - examples/
```

## Performance

Jobs run in **parallel** for maximum speed:
- Typical runtime: 3-5 minutes per job
- Total workflow time: ~5 minutes (all jobs run simultaneously)

## Troubleshooting

### "Snyk token not found"
- Ensure `SNYK_TOKEN` secret is set in repository settings
- Verify the token is valid by running `snyk test` locally

### "No vulnerabilities found"
- This is good! ✅
- Results are still uploaded to GitHub Security tab

### "Scan failed but PR passed"
- Check `continue-on-error: true` is set
- Scans are informational; they upload results but don't block workflow

### Private repo: "SARIF upload failed"
- GitHub Advanced Security license required for private repos
- Public repos: Free

## Best Practices

1. **Review Security Tab Weekly**: Check GitHub Security → Code scanning
2. **Prioritize Fixable Issues**: Focus on "upgradable" vulnerabilities first
3. **Set Expiry Dates**: When ignoring vulnerabilities, always set an expiry
4. **Monitor Trends**: Use Snyk dashboard (when `SNYK_ORG_ID` is configured)
5. **Update Dependencies**: Regular updates reduce vulnerability surface

## Local Testing

To test Snyk scans locally before pushing:

```bash
# Install Snyk CLI
npm install -g snyk

# Authenticate
snyk auth

# Test Python dependencies
snyk test --all-projects

# Test Docker image
docker build -t test-image .
snyk container test test-image --file=Dockerfile

# Test IaC
snyk iac test

# Test code
snyk code test
```

## Further Reading

- [Snyk Documentation](https://docs.snyk.io)
- [Snyk GitHub Actions](https://github.com/snyk/actions)
- [GitHub Code Scanning](https://docs.github.com/en/code-security/code-scanning)
