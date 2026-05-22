# Kagenti Claude Code Skills

Skills provide guided workflows for Claude Code to operate the Kagenti platform.
Each skill is a SKILL.md file that teaches Claude how to perform specific tasks
with copy-pasteable commands and decision trees.

## Table of Contents

- [How Skills Work](#how-skills-work)
- [Workflow Diagrams](#workflow-diagrams)
  - [TDD Workflow](#tdd-workflow)
  - [Test Workflow](#test-workflow)
  - [RCA Workflow](#rca-workflow)
  - [CI Workflow](#ci-workflow)
  - [Playwright Demo Workflow](#playwright-demo-workflow)
  - [Skills Meta Workflow](#skills-meta-workflow)
  - [GitHub Repository Analysis](#github-repository-analysis)
  - [Deploy & Debug Workflow](#deploy--debug-workflow)
  - [HyperShift Cluster Lifecycle](#hypershift-cluster-lifecycle-with-mgmt-creds)
- [Complete Skill Tree](#complete-skill-tree)
- [Auto-Approve Policy](#auto-approve-policy)
- [Maintaining This README](#maintaining-this-readme)

## How Skills Work

- **Invoke**: Use the Skill tool with the skill name (e.g., `tdd:ci`)
- **Parent skills** (e.g., `tdd`) auto-select the right sub-skill based on context
- **Sandbox operations** (Kind/HyperShift hosted clusters) are auto-approved
- **Management operations** (cluster create/destroy, AWS) require user approval
- **Temp files** go to `/tmp/kagenti/<category>/`

## Workflow Diagrams

### Color Legend

Only skill nodes are colored. Decision points, actions, and labels have no color.

| Color | Category |
|-------|----------|
| 🟢 Green | TDD |
| 🔴 Red-Orange | RCA |
| 🔵 Blue | CI |
| 🟣 Purple | Test |
| 🟠 Orange | Git / Repo |
| 🔷 Cyan | Kubernetes |
| 🟤 Brown | Deploy / Kagenti |
| ⚫ Gray | Skills Meta |
| 🩷 Pink | GitHub |
| 🔵 Indigo | HyperShift |
| 🟡 Yellow-Green | Playwright / Demo |
| 🟠 Dark Orange | Session Analytics |

### TDD Workflow (3 Entry Points)

```mermaid
flowchart TD
    START(["/tdd"]) --> INPUT{"What input?"}
    INPUT -->|GH Issue URL| ISSUE[Flow 1: Issue-First]
    INPUT -->|GH PR URL| PR[Flow 2: PR-First]
    INPUT -->|Local doc/task| LOCAL[Flow 3: Local-First]
    INPUT -->|Nothing| DETECT{Detect cluster}

    ISSUE --> ANALYZE[Read issue + conversation]
    ANALYZE --> CHECKPR{"Existing PR?"}
    CHECKPR -->|Own PR| PR
    CHECKPR -->|Other's PR| FORK{Fork or comment?}
    CHECKPR -->|No PR| RESEARCH["rca + plan + post to issue"]:::rca
    FORK --> RESEARCH
    RESEARCH --> WORKTREE["git:worktree"]:::git
    WORKTREE --> TDDCI

    PR --> RCACI["rca:ci"]:::rca
    RCACI --> TDDCI["tdd:ci"]:::tdd
    TDDCI -->|"3+ failures"| HS["tdd:hypershift"]:::tdd
    TDDCI -->|CI green| REVIEWS[Handle PR reviews]

    LOCAL --> KIND["tdd:kind"]:::tdd
    KIND -->|Tests pass| MOVETOPR[Create issue + PR]
    MOVETOPR --> PR

    DETECT -->|HyperShift| HS
    DETECT -->|Kind| KIND
    DETECT -->|None| TDDCI

    HS -->|CI green| REVIEWS
    REVIEWS -->|Changes needed| TDDCI
    REVIEWS -->|Approved| DONE([Merged])

    classDef tdd fill:#4CAF50,stroke:#333,color:white
    classDef rca fill:#FF5722,stroke:#333,color:white
    classDef git fill:#FF9800,stroke:#333,color:white
```

### Test Workflow

```mermaid
flowchart TD
    START([Need Tests]) --> TEST{"/test"}
    TEST -->|Write new tests| WRITE["test:write"]:::test
    TEST -->|Review quality| REVIEW["test:review"]:::test
    TEST -->|Run on Kind| RUNKIND["test:run-kind"]:::test
    TEST -->|Run on HyperShift| RUNHS["test:run-hypershift"]:::test
    TEST -->|Full TDD loop| TDD["tdd/*"]:::tdd

    WRITE --> REVIEW
    REVIEW -->|Issues found| WRITE
    REVIEW -->|Clean| RUN{Run where?}
    RUN -->|Kind| RUNKIND
    RUN -->|HyperShift| RUNHS
    RUNKIND -->|Pass| COMMIT["git:commit"]:::git
    RUNHS -->|Pass| COMMIT
    RUNKIND -->|Fail| WRITE
    RUNHS -->|Fail| WRITE
    COMMIT --> REBASE["git:rebase"]:::git
    REBASE --> PUSH([Push to PR])

    classDef tdd fill:#4CAF50,stroke:#333,color:white
    classDef test fill:#9C27B0,stroke:#333,color:white
    classDef git fill:#FF9800,stroke:#333,color:white
```

### RCA Workflow

```mermaid
flowchart TD
    FAIL([CI / Test Failure]) --> RCA{"/rca"}
    RCA -->|CI failure, no cluster| RCACI["rca:ci"]:::rca
    RCA -->|HyperShift cluster available| RCAHS["rca:hypershift"]:::rca
    RCA -->|Kind cluster available| RCAKIND["rca:kind"]:::rca

    RCACI -->|Inconclusive| NEED{"Need cluster?"}
    NEED -->|Yes| RCAHS
    NEED -->|Reproduce locally| RCAKIND

    RCACI --> ROOT[Root Cause Found]
    RCAHS --> ROOT
    RCAKIND --> ROOT

    ROOT --> TDD["tdd:*"]:::tdd
    TDD --> DONE([Fixed])

    RCAHS -.->|uses| PODS["k8s:pods"]:::k8s
    RCAHS -.->|uses| LOGS["k8s:logs"]:::k8s
    RCAHS -.->|uses| HEALTH["k8s:health"]:::k8s
    RCAHS -.->|uses| LIVE["k8s:live-debugging"]:::k8s

    classDef rca fill:#FF5722,stroke:#333,color:white
    classDef tdd fill:#4CAF50,stroke:#333,color:white
    classDef k8s fill:#00BCD4,stroke:#333,color:white
```

### CI Workflow

```mermaid
flowchart TD
    PR([PR / Push]) --> CI{"/ci"}
    CI -->|Check status| STATUS["ci:status"]:::ci
    CI -->|Monitor running| MON["ci:monitoring"]:::ci
    CI -->|Failed, investigate| RCACI["rca:ci"]:::rca
    CI -->|Failed, fix + rerun| TDDCI["tdd:ci"]:::tdd

    STATUS --> RESULT{Result?}
    RESULT -->|All pass| DONE([Merge])
    RESULT -->|Failed| RCACI
    MON -->|Completed| STATUS

    RCACI --> ROOT[Root Cause]
    ROOT --> TDDCI
    TDDCI -->|CI passes| DONE

    classDef ci fill:#2196F3,stroke:#333,color:white
    classDef rca fill:#FF5722,stroke:#333,color:white
    classDef tdd fill:#4CAF50,stroke:#333,color:white
```

### Playwright Demo Workflow

```mermaid
flowchart TD
    START([Demo Needed]) --> RESEARCH["playwright-research"]:::pw
    RESEARCH -->|UI changes detected| PLAN[Plan demo segments]
    RESEARCH -->|No changes| SKIP([No update needed])

    PLAN --> WRITE["test:playwright"]:::test
    WRITE --> REVIEW["test:review"]:::test
    REVIEW -->|Issues| WRITE
    REVIEW -->|Clean| RECORD["playwright-demo"]:::pw

    RECORD -->|Fails| DEBUG["playwright-demo:debug"]:::pw
    DEBUG --> WRITE
    RECORD -->|Success| VIDEO([Demo video ready])

    classDef pw fill:#8BC34A,stroke:#333,color:white
    classDef test fill:#9C27B0,stroke:#333,color:white
```

### Skills Meta Workflow

```mermaid
flowchart TD
    START([New / Audit Skills]) --> SCAN["skills:scan"]:::skills
    SCAN -->|New repo| WRITE["skills:write"]:::skills
    SCAN -->|Existing repo| VALIDATE["skills:validate"]:::skills
    VALIDATE -->|Issues found| WRITE
    VALIDATE -->|All pass| REPORT[Generate Report]

    WRITE --> VALIDATE
    REPORT --> RETRO["skills:retrospective"]:::skills
    RETRO -->|Gaps found| WRITE
    RETRO -->|Skills OK| README[Update README]

    SCAN -.->|generates| SETTINGS[settings.json]
    SCAN -.->|generates| README

    classDef skills fill:#607D8B,stroke:#333,color:white
```

### GitHub Repository Analysis

```mermaid
flowchart TD
    START([Repo Health Check]) --> GH{"/github"}
    GH -->|Weekly summary| WEEK["github:last-week"]:::github
    GH -->|Triage issues| ISSUES["github:issues"]:::github
    GH -->|PR health| PRS["github:prs"]:::github

    WEEK -->|calls| ISSUES
    WEEK -->|calls| PRS
    WEEK -->|calls| CISTATUS["ci:status"]:::ci

    ISSUES -->|stale/outdated| CLOSE[Close or update issue]
    ISSUES -->|blocking| PRIORITY[Flag for immediate action]
    PRS -->|ready to merge| REVIEW[Request review]
    PRS -->|conflicts| REBASE["git:rebase"]:::git
    PRS -->|CI failing| RCA["rca:ci"]:::rca

    CLOSE -.->|create updated| REPOISSUE["repo:issue"]:::git

    classDef github fill:#E91E63,stroke:#333,color:white
    classDef git fill:#FF9800,stroke:#333,color:white
    classDef ci fill:#2196F3,stroke:#333,color:white
    classDef rca fill:#FF5722,stroke:#333,color:white
```

### Deploy & Debug Workflow

```mermaid
flowchart TD
    DEPLOY([Deploy Kagenti]) --> TYPE{Platform?}
    TYPE -->|Kind| KDEPLOY["kagenti:deploy"]:::deploy
    TYPE -->|OpenShift| ODEPLOY["kagenti:deploy"]:::deploy
    TYPE -->|HyperShift| HSDEPLOY["kagenti:operator"]:::deploy

    KDEPLOY --> HEALTH["k8s:health"]:::k8s
    ODEPLOY --> HEALTH
    HSDEPLOY --> HEALTH

    HEALTH -->|Healthy| DONE([Ready])
    HEALTH -->|Issues| DEBUG{Debug}
    DEBUG -->|Pod issues| PODS["k8s:pods"]:::k8s
    DEBUG -->|Log analysis| LOGS["k8s:logs"]:::k8s
    DEBUG -->|Helm issues| HELM["helm:debug"]:::deploy
    DEBUG -->|UI issues| UI["kagenti:ui-debug"]:::deploy
    DEBUG -->|Auth issues| AUTH["auth:keycloak-*"]:::deploy
    DEBUG -->|Istio issues| ISTIO["istio:ambient-waypoint"]:::deploy
    DEBUG -->|Route issues| ROUTES["openshift:routes"]:::deploy

    PODS --> HEALTH
    LOGS --> HEALTH
    HELM --> HEALTH

    classDef deploy fill:#795548,stroke:#333,color:white
    classDef k8s fill:#00BCD4,stroke:#333,color:white
```

### Session Analytics Workflow

```mermaid
flowchart TD
    START([Session Analytics]) --> SESSION{"/session"}
    SESSION -->|Post stats| POST["session:post"]:::session
    SESSION -->|Update summary| SUMMARY["session:summary"]:::session
    SESSION -->|Extract data| EXTRACT["session:extract"]:::session
    SESSION -->|Dashboard| DASHBOARD["session:dashboard"]:::session

    POST -->|calls| SUMMARY
    EXTRACT -->|generates| DASHBOARD

    POST -.->|uses| STATS["--phase stats"]
    POST -.->|uses| MERMAID["--phase mermaid"]

    classDef session fill:#FF6F00,stroke:#333,color:white
```

### HyperShift Cluster Lifecycle (with mgmt creds)

```mermaid
flowchart LR
    SETUP["hypershift:setup"]:::hypershift --> PREFLIGHT["hypershift:preflight"]:::hypershift
    PREFLIGHT --> QUOTAS["hypershift:quotas"]:::hypershift
    QUOTAS --> CREATE["hypershift:cluster create"]:::hypershift
    CREATE --> USE([Use cluster])
    USE --> DESTROY["hypershift:cluster destroy"]:::hypershift

    CREATE -.->|fails| DEBUG["hypershift:debug"]:::hypershift
    DESTROY -.->|stuck| DEBUG

    classDef hypershift fill:#3F51B5,stroke:#333,color:white
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
│   ├── github:my-status
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
├── playwright-demo/                Demo video recording
│   └── playwright-demo:debug
├── playwright-research/            Demo lifecycle management
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
│   ├── test:playwright
│   ├── test:write
│   ├── test:review
│   ├── test:run-kind
│   └── test:run-hypershift
├── repo/                           Repository conventions
│   ├── repo:pr
│   └── repo:issue
├── session/                       Session analytics
│   ├── session:post
│   ├── session:summary
│   ├── session:extract
│   └── session:dashboard
└── testing:kubectl-debugging       Common kubectl debugging commands
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
