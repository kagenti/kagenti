# Kagenti Claude Code Skills

Skills provide guided workflows for Claude Code to operate the Kagenti platform.
Each skill is a SKILL.md file that teaches Claude how to perform specific tasks
with copy-pasteable commands and decision trees.

## How Skills Work

- **Invoke**: Use the Skill tool with the skill name (e.g., `tdd:ci`)
- **Parent skills** (e.g., `tdd`) auto-select the right sub-skill based on context
- **Sandbox operations** (Kind/HyperShift hosted clusters) are auto-approved
- **Management operations** (cluster create/destroy, AWS) require user approval
- **Temp files** go to `/tmp/kagenti/<category>/`

## Workflow Diagrams

### TDD Workflow

```mermaid
flowchart TD
    START([Task / Bug]) --> TDD{"/tdd"}
    TDD -->|HyperShift cluster found| HS["tdd:hypershift"]
    TDD -->|Kind cluster found| KIND["tdd:kind"]
    TDD -->|No cluster| CI["tdd:ci"]
    TDD -->|No cluster, ask user| CREATE{"Create cluster?"}
    CREATE -->|Kind auto-approved| KIND
    CREATE -->|HyperShift needs approval| HS
    CREATE -->|No| CI

    CI -->|"3+ failures"| ESCALATE{"Escalate?"}
    ESCALATE -->|Yes| HS
    ESCALATE -->|No| CI

    HS --> CODE[Write/Fix Code]
    KIND --> CODE
    CI --> CODE

    CODE --> TESTLOOP["test:write + test:review"]
    TESTLOOP --> RUN{Run tests}
    RUN -->|Kind| RUNKIND["test:run-kind"]
    RUN -->|HyperShift| RUNHS["test:run-hypershift"]
    RUNKIND -->|More failures than before| CODE
    RUNHS -->|More failures than before| CODE
    RUNKIND -->|"Fewer failures (progress!)"| COMMIT["git:commit + git:rebase"]
    RUNHS -->|"Fewer failures (progress!)"| COMMIT
    COMMIT --> PUSH[Push to PR]
    PUSH --> MONITOR["ci:monitoring (wait)"]
    MONITOR -->|CI passes| DONE([Done])
    MONITOR -->|CI fails| CODE
```

### Test Workflow

```mermaid
flowchart TD
    START([Need Tests]) --> TEST{"/test"}
    TEST -->|Write new tests| WRITE["test:write"]
    TEST -->|Review quality| REVIEW["test:review"]
    TEST -->|Run on Kind| RUNKIND["test:run-kind"]
    TEST -->|Run on HyperShift| RUNHS["test:run-hypershift"]
    TEST -->|Full TDD loop| TDD["tdd/*"]

    WRITE --> REVIEW
    REVIEW -->|Issues found| WRITE
    REVIEW -->|Clean| RUN{Run where?}
    RUN -->|Kind| RUNKIND
    RUN -->|HyperShift| RUNHS
    RUNKIND -->|Pass| COMMIT["git:commit"]
    RUNHS -->|Pass| COMMIT
    RUNKIND -->|Fail| WRITE
    RUNHS -->|Fail| WRITE
    COMMIT --> REBASE["git:rebase"]
    REBASE --> PUSH([Push to PR])
```

### RCA Workflow

```mermaid
flowchart TD
    FAIL([CI / Test Failure]) --> RCA{"/rca"}
    RCA -->|CI failure, no cluster| RCACI["rca:ci"]
    RCA -->|HyperShift cluster available| RCAHS["rca:hypershift"]
    RCA -->|Kind cluster available| RCAKIND["rca:kind"]

    RCACI -->|Inconclusive| NEED{"Need cluster?"}
    NEED -->|Yes| RCAHS
    NEED -->|Reproduce locally| RCAKIND

    RCACI --> ROOT[Root Cause Found]
    RCAHS --> ROOT
    RCAKIND --> ROOT

    ROOT --> TDD["Switch to tdd:* for fix"]
    TDD --> DONE([Fixed])

    RCAHS -.->|uses| PODS["k8s:pods"]
    RCAHS -.->|uses| LOGS["k8s:logs"]
    RCAHS -.->|uses| HEALTH["k8s:health"]
    RCAHS -.->|uses| LIVE["k8s:live-debugging"]
```

### CI Workflow

```mermaid
flowchart TD
    PR([PR / Push]) --> CI{"/ci"}
    CI -->|Check status| STATUS["ci:status"]
    CI -->|Monitor running| MON["ci:monitoring"]
    CI -->|Failed, investigate| RCACI["rca:ci"]
    CI -->|Failed, fix + rerun| TDDCI["tdd:ci"]

    STATUS --> RESULT{Result?}
    RESULT -->|All pass| DONE([Merge])
    RESULT -->|Failed| RCACI
    MON -->|Completed| STATUS

    RCACI --> ROOT[Root Cause]
    ROOT --> TDDCI
    TDDCI -->|CI passes| DONE
```

### Skills Meta Workflow

```mermaid
flowchart TD
    START([New / Audit Skills]) --> SCAN["skills:scan"]
    SCAN -->|New repo| WRITE["skills:write"]
    SCAN -->|Existing repo| VALIDATE["skills:validate"]
    VALIDATE -->|Issues found| WRITE
    VALIDATE -->|All pass| REPORT["Generate Report"]

    WRITE --> VALIDATE
    REPORT --> RETRO["skills:retrospective"]
    RETRO -->|Gaps found| WRITE
    RETRO -->|Skills OK| README["Update README diagrams"]

    SCAN -.->|generates| SETTINGS["settings.json"]
    SCAN -.->|generates| README
```

### GitHub Repository Analysis

```mermaid
flowchart TD
    START([Repo Health Check]) --> GH{"/github"}
    GH -->|Weekly summary| WEEK["github:last-week"]
    GH -->|Triage issues| ISSUES["github:issues"]
    GH -->|PR health| PRS["github:prs"]

    WEEK -->|calls| ISSUES
    WEEK -->|calls| PRS
    WEEK -->|calls| CISTATUS["ci:status"]

    ISSUES -->|stale/outdated| CLOSE["Close or update issue"]
    ISSUES -->|blocking| PRIORITY["Flag for immediate action"]
    PRS -->|ready to merge| REVIEW["Request review"]
    PRS -->|conflicts| REBASE["git:rebase"]
    PRS -->|CI failing| RCA["rca:ci"]

    CLOSE -.->|create updated| REPOISSUE["repo:issue"]
```

### Deploy & Debug Workflow

```mermaid
flowchart TD
    DEPLOY([Deploy Kagenti]) --> TYPE{Platform?}
    TYPE -->|Kind| KDEPLOY["kagenti:deploy"]
    TYPE -->|OpenShift| ODEPLOY["kagenti:deploy"]
    TYPE -->|HyperShift| HSDEPLOY["kagenti:operator"]

    KDEPLOY --> HEALTH["k8s:health"]
    ODEPLOY --> HEALTH
    HSDEPLOY --> HEALTH

    HEALTH -->|Healthy| DONE([Ready])
    HEALTH -->|Issues| DEBUG{Debug}
    DEBUG -->|Pod issues| PODS["k8s:pods"]
    DEBUG -->|Log analysis| LOGS["k8s:logs"]
    DEBUG -->|Helm issues| HELM["helm:debug"]
    DEBUG -->|UI issues| UI["kagenti:ui-debug"]
    DEBUG -->|Auth issues| AUTH["auth:keycloak-*"]
    DEBUG -->|Istio issues| ISTIO["istio:ambient-waypoint"]
    DEBUG -->|Route issues| ROUTES["openshift:routes"]

    PODS --> HEALTH
    LOGS --> HEALTH
    HELM --> HEALTH
```

### HyperShift Cluster Lifecycle (with mgmt creds)

```mermaid
flowchart LR
    SETUP["hypershift:setup"] --> PREFLIGHT["hypershift:preflight"]
    PREFLIGHT --> QUOTAS["hypershift:quotas"]
    QUOTAS --> CREATE["hypershift:cluster create"]
    CREATE --> USE([Use cluster])
    USE --> DESTROY["hypershift:cluster destroy"]

    CREATE -.->|fails| DEBUG["hypershift:debug"]
    DESTROY -.->|stuck| DEBUG
```

## Complete Skill Tree

```
├── auth/                           OAuth2 & Keycloak patterns
│   ├── auth:keycloak-confidential-client
│   ├── auth:mlflow-oidc-auth
│   └── auth:otel-oauth2-exporter
├── ci/                             CI pipeline management (smart router)
│   ├── ci:status
│   └── ci:monitoring
├── genai/                          GenAI observability
│   └── genai:semantic-conventions
├── github/                         Repository health & analysis
│   ├── github:last-week
│   ├── github:issues
│   └── github:prs
├── git/                            Git operations
│   ├── git:status
│   ├── git:worktree
│   ├── git:rebase
│   └── git:commit
├── helm/                           Helm chart debugging
│   └── helm:debug
├── hypershift/                     HyperShift cluster lifecycle
│   ├── hypershift:cluster
│   ├── hypershift:debug
│   ├── hypershift:preflight
│   ├── hypershift:quotas
│   └── hypershift:setup
├── istio/                          Service mesh patterns
│   └── istio:ambient-waypoint
├── k8s/                            Kubernetes debugging
│   ├── k8s:health
│   ├── k8s:logs
│   ├── k8s:pods
│   └── k8s:live-debugging
├── kagenti/                        Platform management
│   ├── kagenti:deploy
│   ├── kagenti:operator
│   └── kagenti:ui-debug
├── kind/                           Local Kind clusters
│   └── kind:cluster
├── local/                          Local testing workflows
│   ├── local:full-test
│   └── local:testing
├── meta/                           Documentation
│   └── meta:write-docs
├── openshift/                      OpenShift operations
│   ├── openshift:debug
│   ├── openshift:routes
│   └── openshift:trusted-ca-bundle
├── rca/                            Root cause analysis (smart router)
│   ├── rca:ci
│   ├── rca:hypershift
│   └── rca:kind
├── skills/                         Skill management
│   ├── skills:scan
│   ├── skills:write
│   ├── skills:validate
│   └── skills:retrospective
├── tdd/                            TDD workflows (smart router)
│   ├── tdd:ci
│   ├── tdd:hypershift
│   └── tdd:kind
├── test/                           Test management (smart router)
│   ├── test:write
│   ├── test:review
│   ├── test:run-kind
│   └── test:run-hypershift
├── repo/                           Repository conventions
│   ├── repo:commit
│   ├── repo:pr
│   └── repo:issue
└── testing/                        Debugging techniques
    └── testing:kubectl-debugging
```

## Auto-Approve Policy

| Target | Read | Write | Create/Destroy |
|--------|------|-------|----------------|
| Kind cluster | Auto | Auto | Auto |
| HyperShift hosted cluster | Auto | Auto | N/A |
| HyperShift management cluster | Auto | Approval | Approval |
| AWS resources | Auto | Approval | Approval |
| `/tmp/kagenti/` | Auto | Auto | Auto |
| Git operations | Auto | Auto | N/A |

## Maintaining This README

This README is generated by `skills:scan`. Run it to update the diagrams
and connection analysis after adding or modifying skills.
