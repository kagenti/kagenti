# Security Policy

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue,
please report it responsibly.

### How to Report

1. **Do NOT create public GitHub issues** for security vulnerabilities
2. **GitHub Security Advisories (preferred)**: Report vulnerabilities privately via
   [GitHub Security Advisories](../../security/advisories/new)
3. **Email**: Send reports to **security@kagenti.io**
4. **Include**: A clear description of the vulnerability, steps to reproduce,
   affected versions, and potential impact

### Security Contacts

- **kagenti-maintainers@googlegroups.com**
- **security@kagenti.io**

### What to Expect

- **Acknowledgement**: within 48 hours of receipt
- **Initial assessment**: within 7 business days
- **Resolution timeline**: critical vulnerabilities within 30 days, others within 90 days
- **Credit**: We will credit you in the security advisory (if desired)
- **Updates**: We will keep you informed of our progress throughout the process

### Disclosure Policy

We follow [coordinated vulnerability disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure).
Please allow us reasonable time to address the vulnerability before any public
disclosure. We aim to publish fixes and advisories within 90 days of the initial report.

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| main    | :white_check_mark: |

Only the latest release and the `main` branch receive security updates.

## Security Measures

This project implements several security controls:

- **CI/CD Security**: All workflows use explicit least-privilege permissions with
  hash-pinned GitHub Actions
- **Dependency Scanning**: Automated vulnerability scanning via Trivy and Dependabot
  with weekly update cadence
- **Secret Detection**: Pre-commit hooks with Gitleaks for secret scanning
- **Code Analysis**: CodeQL and Bandit for static analysis
- **Container Security**: Hadolint for Dockerfile best practices, base images pinned
  to sha256 digests
- **Supply Chain**: OpenSSF Scorecard monitoring, SLSA-compliant build process
- **Runtime Security**: Istio Ambient mTLS, SPIFFE workload identity, Landlock/seccomp
  sandboxing for agent execution

## Security-Related Configuration

For deployment security configuration, see:
- [docs/install.md](docs/install.md) - Installation and security setup
- [deployments/envs/](deployments/envs/) - Environment-specific configurations
