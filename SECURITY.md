# Security Policy

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue,
please report it responsibly.

### How to Report

1. **Do NOT create public GitHub issues** for security vulnerabilities
2. **Email**: Report vulnerabilities privately via GitHub Security Advisories
   - Go to the [Security tab](../../security/advisories/new) and create a new advisory
3. **Include**: A clear description of the vulnerability, steps to reproduce,
   and potential impact

### What to Expect

- We will acknowledge receipt within 48 hours
- We aim to provide an initial assessment within 7 days
- We will keep you informed of our progress
- We will credit you in the security advisory (if desired)

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |

## Security Measures

This project implements several security controls:

- **CI/CD Security**: All workflows use explicit least-privilege permissions
- **Dependency Scanning**: Automated vulnerability scanning via Trivy and Dependabot
- **Secret Detection**: Pre-commit hooks with Gitleaks for secret scanning
- **Code Analysis**: CodeQL and Bandit for static analysis
- **Container Security**: Hadolint for Dockerfile best practices

## Security-Related Configuration

For deployment security configuration, see:
- [docs/install.md](docs/install.md) - Installation and security setup
- [deployments/envs/](deployments/envs/) - Environment-specific configurations
