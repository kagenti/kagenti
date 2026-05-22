---
name: github
description: GitHub repository analysis - weekly reports, issue triage, PR health, CI trends
---

```mermaid
flowchart TD
    START([Repo Health]) --> GH{"/github"}
    GH -->|My status| MYSTATUS["github:my-status"]:::github
    GH -->|Weekly summary| WEEK["github:last-week"]:::github
    GH -->|Org-wide weekly| ORGWEEK["github:last-week-org"]:::github
    GH -->|Triage issues| ISSUES["github:issues"]:::github
    GH -->|PR health| PRS["github:prs"]:::github
    GH -->|Review PR| PRREVIEW["github:pr-review"]:::github
    GH -->|Dependabot triage| DEPBOT["github:dependabot"]:::github

    ORGWEEK -->|calls per repo| WEEK
    WEEK -->|calls| ISSUES
    WEEK -->|calls| PRS
    ISSUES -->|stale| CLOSE[Close or update]
    PRS -->|CI failing| RCA["rca:ci"]:::rca

    classDef github fill:#E91E63,stroke:#333,color:white
    classDef rca fill:#FF5722,stroke:#333,color:white
```

> Follow this diagram as the workflow.

# GitHub Skills

Repository health analysis, issue triage, and PR management.

## Variables

Set at session start:

```bash
export OWNER=<org-or-user>
export REPO=<repo-name>
```

## Auto-Select Sub-Skill

```
What do you need?
    │
    ├─ What needs my attention today?
    │   → github:my-status
    │
    ├─ Weekly summary (what happened last week?)
    │   ├─ Single repo ($OWNER/$REPO)
    │   │   → github:last-week
    │   └─ Org-wide (all repos)
    │       → github:last-week-org
    │
    ├─ Analyze open issues (triage, stale, priority)
    │   → github:issues
    │
    ├─ Analyze open PRs (CI status, review needed)
    │   → github:prs
    │
    ├─ Review a specific PR (inline comments, conventions)
    │   → github:pr-review
    │
    ├─ Triage Dependabot PRs (categorize, bundle, merge)
    │   → github:dependabot
    │
    └─ Create an issue with proper template
        → repo:issue
```

## Available Skills

| Skill | Purpose |
|-------|---------|
| `github:my-status` | Personal dashboard: your open PRs, pending reviews, assigned issues |
| `github:last-week` | Weekly report: merged PRs, new issues, CI health, priority analysis |
| `github:last-week-org` | Org-wide weekly report: all kagenti repos, proportional depth by activity |
| `github:issues` | Issue triage: stale, blocking, no attention, should-close |
| `github:pr-review` | Automated PR review: inline comments, conventions, security checks |
| `github:prs` | PR health: passing CI without review, stale, conflicts |
| `github:dependabot` | Dependabot triage: categorize, bundle, fix CI blockers, approve merges |

## Related Skills

- `repo:issue` - Issue template format
- `repo:pr` - PR template format
- `ci:status` - CI check details
- `ci:monitoring` - Monitor running CI
