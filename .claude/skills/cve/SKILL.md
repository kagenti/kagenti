---
name: cve
description: CVE awareness - scan dependencies for vulnerabilities, plan responsible disclosure, block public leaks
---

# CVE Awareness

Detect CVEs in project dependencies and ensure responsible disclosure before any
public communication.

## IMPORTANT

Accidental public CVE disclosure enables exploitation before patches exist,
violates responsible disclosure agreements, and causes legal and reputational harm.
**Never include CVE IDs, vulnerability descriptions, or exploit details in any
public output** (PRs, issues, comments, commit messages) until the CVE has been
reported through proper channels.

## Router

When `/cve` is invoked, determine the entry point:

```
What is needed?
    |
    +-- "Scan for CVEs" / "Check dependencies"
    |   -> cve:scan
    |
    +-- CVE was found, need response plan
    |   -> cve:brainstorm
    |
    +-- No specific request
        -> cve:scan (default: scan first)
```

## When This Runs Automatically

These skills are invoked as mandatory gates in other workflows:

| Workflow | Gate Location | Skill |
|----------|---------------|-------|
| `tdd:ci` | Phase 3.5 (after local checks, before push) | `cve:scan` |
| `tdd:hypershift` | Pre-deploy (before cluster deployment) | `cve:scan` |
| `tdd:kind` | Pre-deploy (before cluster deployment) | `cve:scan` |
| `rca:*` | Phase 5 addendum (before documenting findings) | `cve:scan` |
| `git:commit` | Pre-commit (scan for CVE IDs in message) | CVE ID check |
| Finishing branch | Step 2.5 (before PR creation options) | `cve:scan` |

## Related Skills

- `cve:scan` - Hybrid CVE scanning (Trivy + LLM + WebSearch)
- `cve:brainstorm` - Disclosure planning and public output blocking
