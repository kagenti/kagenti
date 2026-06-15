# Kagenti Documentation Audit & Reorganization Proposal

**Date:** 2026-05-08
**Scope:** Full documentation audit, CNCF best practices alignment, and migration plan

---

## 1. CNCF Best Practices Applied

### Research Summary

Examined documentation structures from 5 CNCF graduated/incubating projects: Kubernetes, Helm, Argo CD, OpenTelemetry, and Dapr.

**Most relevant model for kagenti: Argo CD** — keeps docs in-repo under `/docs`, uses persona-based separation (`operator-manual/`, `user-guide/`, `developer-guide/`), and uses MkDocs for publishing. This is the closest fit because:
- Kagenti already has all docs in-repo (no separate docs repo)
- The project has distinct personas (platform admins, agent developers, contributors)
- Moderate doc volume (~120 files) that doesn't warrant a separate repo yet

### Patterns Applied

| Pattern | Source | Application to Kagenti |
|---------|--------|----------------------|
| Persona-based folder separation | Argo CD | Split into `user-guide/`, `operator-guide/`, `development/` |
| Diataxis quadrants | Kubernetes | Concepts, How-to, Reference, Getting Started |
| Top-level governance files | All projects | README, CONTRIBUTING, CHANGELOG, SECURITY, CODE_OF_CONDUCT, GOVERNANCE |
| OWNERS/CODEOWNERS per directory | Kubernetes | Add `CODEOWNERS` entries for doc paths |
| Document status markers | OpenTelemetry | Add status (Draft/Stable/Deprecated) to design docs |
| Architecture Decision Records | Argo CD, Dapr | Preserve *why* behind decisions; delete implementation details |
| Active proposals separate from decisions | Argo CD | `docs/proposals/` for in-flight RFCs, `docs/adr/` for decided |
| Runbooks separate from user docs | Dapr | `docs/maintainers/` for operational procedures |

---

## 2. Docs to Remove

| File | Justification |
|------|---------------|
| `AUTO-LABELING-FIX.md` | One-time bug fix note (2026-03-06). Belongs as a commit message or issue comment, not a root-level file. |
| `TODO_CUSTOM_VISUALIZATIONS.md` | Internal passover document. Should be a GitHub issue. |
| `docs/retrospectives/SKILL_RETROSPECTIVE_2026-04-14.md` | Internal session retrospective. No value to external users or contributors. |
| `docs/agentic-runtime/questions.md` | Internal investigation notes with "OPEN"/"BLOCKED" markers. Not documentation. |
| `docs/plans/migrate-agent-crd-to-workloads.md` | All phases completed. No longer relevant. |
| `docs/plans/migrate-tool-mcpserver-to-workloads.md` | All 6 phases completed. No longer relevant. |
| `docs/plans/shipwright-refactoring-plan.md` | All 3 phases completed. No longer relevant. |
| `docs/plans/2026-02-15-session-metadata-analytics-design.md` | Draft status, potentially abandoned. |
| `docs/plans/2026-02-15-session-metadata-analytics-impl.md` | Implementation plan for abandoned design above. |
| `docs/2025-10.Kagenti-Identity.pdf` | Binary PDF in docs folder. Should be linked externally or converted to markdown. |
| `docs/blogs.md` | Just a list of links to external blog posts (last updated 2025-12-09). Can be a section in README or removed. |

**Total: 11 files to remove/archive (saving ~3000 lines of stale content)**

---

## 3. Docs to Update

### Critical Fixes (Broken References)

| File | Issue | Fix |
|------|-------|-----|
| `CLAUDE.md` | References `docs/auth/keycloak-patterns.md`, `docs/skills/README.md`, `docs/ai-ops/README.md` — none exist | Replace `docs/auth/keycloak-patterns.md` with `docs/authbridge/` (after PR #1476); remove or create the other two |
| `CLAUDE.md` | Feature flag table lists 3 flags, code has 7 | Add `agent_sandbox`, `authbridge_api`, `skills`, `sidecars` |
| `docs/gateway.md` | References `--skip-install mcp_gateway` flag that doesn't exist | Replace with `--with-mcp-gateway` (the actual opt-in flag) |
| `docs/research/openshell-mvp.md` | Links to `openshell-k8s-integration.md` and `openshell-driver-architecture.md` — don't exist | Remove dead links or create the referenced docs |
| `docs/user-stories.md` | Links to `agentic-runtime/use-cases.md` — doesn't exist | Update link target |
| `kagenti/auth/README.md` | Only lists 2 of 4 subdirectories | Add `api-oauth-secret` and `spiffe-idp-setup` |

### Content Corrections

| File | Issue | Fix |
|------|-------|-----|
| `README.md` line 73 | References "Langflow" for observability | Replace with "Phoenix" (actual tool) |
| `PERSONAS_AND_ROLES.md` | Lists "Llama Stack" and "BeeAI" as supported frameworks | Remove — neither exists in codebase |
| `docs/plans/2025-02-05-api-bearer-token-auth-design.md` | Status: "Draft" but feature is fully implemented | Update status to "Implemented" |
| `docs/tech-details.md` | Shows `default` namespace for workloads | Update to `team1`/`team2` |
| `kagenti/installer/README.md` | Describes "Agent Lifecycle Operator" managing agent deployments | Update: backend deploys agents directly as Deployments post-migration |
| `docs/identity-guide.md` | Hardcoded `"password"` and `"admin"` without security warning | Add security notice: "LOCAL DEVELOPMENT ONLY" |

---

## 4. Proposed New Structure

```
kagenti/
├── README.md                          # Project overview, badges, quickstart link
├── CONTRIBUTING.md                    # How to contribute (code + docs)
├── CHANGELOG.md                       # Release history (NEW)
├── CODE_OF_CONDUCT.md                 # Community standards
├── GOVERNANCE.md                      # Decision-making process
├── MAINTAINERS.md                     # Project maintainers
├── SECURITY.md                        # Vulnerability reporting
├── CONTRIBUTOR_LADDER.md              # Contributor roles
├── PERSONAS_AND_ROLES.md              # Kagenti user personas
│
├── docs/
│   ├── README.md                      # Doc index with navigation
│   │
│   ├── getting-started/
│   │   ├── why-kagenti.md             # Value proposition + key concepts (NEW)
│   │   ├── quickstart.md              # Zero-to-running in 15 min (NEW)
│   │   ├── installation.md            # Install on Kind + OpenShift
│   │   ├── configuration.md           # Essential config for first deploy (NEW)
│   │   └── troubleshooting.md         # Common issues and fixes
│   │
│   ├── concepts/
│   │   ├── architecture.md            # High-level architecture + diagrams
│   │   ├── components.md              # Component descriptions
│   │   ├── identity-and-auth.md       # Identity/auth model explained
│   │   ├── agent-lifecycle.md         # How agents are deployed and managed (NEW)
│   │   ├── protocols.md               # A2A + MCP protocol overview (NEW)
│   │   └── sandboxing.md              # Sandbox isolation layers
│   │
│   ├── user-guide/
│   │   ├── importing-agents.md        # How to import an agent
│   │   ├── importing-tools.md         # How to import an MCP tool
│   │   ├── mcp-gateway.md             # MCP Gateway usage
│   │   ├── local-models.md            # Using Ollama/local models
│   │   ├── sandbox.md                 # OpenShell sandbox usage
│   │   ├── api-authentication.md      # API bearer token auth
│   │   └── mlflow-integration.md      # MLflow tracing setup
│   │
│   ├── operator-guide/
│   │   ├── openshift-install.md       # OpenShift-specific deployment
│   │   ├── helm-values-reference.md   # Helm values ref (NEW, auto-gen from operator)
│   │   ├── config-reference.md        # Env vars + config (NEW, auto-gen from operator)
│   │   ├── feature-flags.md           # All feature flags documented (NEW)
│   │   ├── identity-guide.md          # Keycloak/SPIFFE/OIDC deep dive
│   │   └── monitoring.md              # Kiali, Phoenix, observability (NEW)
│   │
│   ├── authbridge/                        # Component deep-dive (PR #1476)
│   │   ├── README.md                  # Hub: architecture, persona links
│   │   ├── security-model.md          # Trust model, token exchange, SPIFFE, threats
│   │   ├── deployment-guide.md        # Proxy-sidecar vs envoy-sidecar, config ref
│   │   ├── demos.md                   # Progressive 5-layer demo path
│   │   └── roadmap.md                 # Current state + near-term epics
│   │
│   ├── demos/
│   │   ├── README.md                  # Demo index
│   │   ├── weather-agent.md           # Weather agent demo
│   │   ├── github-issue-agent.md      # GitHub issue agent demo
│   │   ├── file-organizer-agent.md    # File organizer demo
│   │   ├── generic-agent.md           # Generic agent demo
│   │   ├── image-agent.md             # Image agent demo
│   │   └── slack-research-agent.md    # Slack research demo
│   │
│   ├── reference/
│   │   ├── api.md                     # API endpoint reference (NEW - link to /api/docs)
│   │   ├── cli.md                     # CLI/script reference (NEW)
│   │   └── agent-catalog.md           # Available agent types
│   │
│   ├── development/
│   │   ├── README.md                  # Developer guide index
│   │   ├── local-dev-kind.md          # Kind local development
│   │   ├── local-dev-hypershift.md    # HyperShift development
│   │   ├── claude-code.md             # Claude Code AI development
│   │   ├── windows-wsl-setup.md       # Windows WSL setup
│   │   └── releasing.md               # Release process
│   │
│   ├── adr/                               # Architecture Decision Records
│   │   ├── README.md                  # ADR process + template (NEW)
│   │   ├── 001-api-bearer-token-auth.md       # Decided: bearer token auth model
│   │   ├── 002-agent-context-isolation.md     # Decided: sandbox isolation approach
│   │   ├── 003-istio-shared-trust.md          # Active: cross-namespace trust
│   │   └── 004-agent-sandbox-workload-type.md # Decided: direct sandbox creation
│   │
│   ├── proposals/
│   │   ├── README.md                  # Proposal process + template (NEW)
│   │   └── 2026-02-24-orchestrate-ci-expansion.md # Active proposal
│   │
│   ├── maintainers/
│   │   ├── release-sop.md             # Release governance SOP
│   │   ├── rotate-hypershift-ci-credentials.md
│   │   └── upgrade-guide.md           # Version upgrade procedures (NEW)
│   │
│   ├── research/
│   │   ├── openshell-mvp.md           # OpenShell MVP design
│   │   └── use-case-types.md          # Agent use case taxonomy
│   │
│   └── images/                            # Shared diagrams and screenshots
```

### Note: Coordination with PR #1476 (AuthBridge Docs)

PR [#1476](https://github.com/kagenti/kagenti/pull/1476) adds a comprehensive `docs/authbridge/` section (949 lines, 5 files) organized by persona. It should be **merged first** since it is concrete and ready to land. This reorg proposal treats `docs/authbridge/` as a "keep in place" component deep-dive section.

**Why a standalone section (not split across persona folders):**
AuthBridge spans all audiences — security architects (trust model), operators (deployment), and users (demos). Splitting it would break the narrative flow. This mirrors how Argo CD keeps `docs/operator-manual/notifications/` as self-contained rather than scattering it.

**Cross-links to add after both PRs land:**
- `docs/concepts/identity-and-auth.md` → link to `docs/authbridge/security-model.md`
- `docs/operator-guide/identity-guide.md` → link to `docs/authbridge/deployment-guide.md`
- `docs/demos/README.md` → reference `docs/authbridge/demos.md` in the demo index
- `CLAUDE.md` → replace dead `docs/auth/keycloak-patterns.md` link with `docs/authbridge/`

**The missing `docs/auth/` directory** referenced in CLAUDE.md is effectively fulfilled by `docs/authbridge/`. After PR #1476 merges, update CLAUDE.md to point there instead.

---

## 5. Migration Plan

### Migration Mapping Table

| Current File | Action | Target Path | Reason |
|---|---|---|---|
| `AUTO-LABELING-FIX.md` | **DELETE** | — | Sprint note, no lasting value |
| `TODO_CUSTOM_VISUALIZATIONS.md` | **DELETE** | — | Convert to GitHub issue |
| `docs/blogs.md` | **DELETE** | — | Stale link list (Dec 2025), add to README if needed |
| `docs/2025-10.Kagenti-Identity.pdf` | **DELETE** | — | Binary file in docs; link externally if needed |
| `docs/retrospectives/` | **DELETE** | — | Internal retro with no external value |
| `docs/agentic-runtime/questions.md` | **DELETE** | — | Internal investigation notes |
| `docs/install.md` | **MOVE + UPDATE** | `docs/getting-started/installation.md` | User-facing, needs command verification |
| `docs/troubleshooting.md` | **MOVE** | `docs/getting-started/troubleshooting.md` | Keep with install docs |
| `docs/components.md` | **MOVE + UPDATE** | `docs/concepts/components.md` | Update stale references |
| `docs/tech-details.md` | **MOVE + UPDATE** | `docs/concepts/architecture.md` | Rename, update namespace refs |
| `docs/identity-guide.md` | **MOVE + UPDATE** | `docs/operator-guide/identity-guide.md` | Add security notice for demo creds |
| `docs/api-authentication.md` | **MOVE** | `docs/user-guide/api-authentication.md` | User-facing how-to |
| `docs/new-agent.md` | **MOVE** | `docs/user-guide/importing-agents.md` | Rename for clarity |
| `docs/new-tool.md` | **MOVE** | `docs/user-guide/importing-tools.md` | Rename for clarity |
| `docs/gateway.md` | **MOVE + UPDATE** | `docs/user-guide/mcp-gateway.md` | Fix `--skip-install` reference |
| `docs/local-models.md` | **MOVE** | `docs/user-guide/local-models.md` | User-facing |
| `docs/sandbox-guide.md` | **MOVE** | `docs/user-guide/sandbox.md` | User-facing |
| `docs/mlflow-integration.md` | **MOVE** | `docs/user-guide/mlflow-integration.md` | User-facing |
| `docs/ocp/openshift-install.md` | **MOVE** | `docs/operator-guide/openshift-install.md` | Operator-facing |
| `docs/kiali/README.md` | **MOVE** | `docs/operator-guide/monitoring.md` | Merge into monitoring guide |
| `docs/dev-guide.md` | **MOVE** | `docs/development/README.md` | Developer index |
| `docs/developer/kind.md` | **MOVE** | `docs/development/local-dev-kind.md` | Clearer name |
| `docs/developer/hypershift.md` | **MOVE** | `docs/development/local-dev-hypershift.md` | Clearer name |
| `docs/developer/claude-code.md` | **MOVE** | `docs/development/claude-code.md` | Keep as-is |
| `docs/developer/claude-code-daily-commands.md` | **DELETE** | — | Redundant with skills docs |
| `docs/developer/claude-code-skills.md` | **DELETE** | — | Redundant with skills system itself |
| `docs/developer/windows-wsl-setup.md` | **MOVE** | `docs/development/windows-wsl-setup.md` | Keep |
| `docs/releasing.md` | **MOVE** | `docs/development/releasing.md` | Contributor process |
| `docs/release-sop.md` | **MOVE** | `docs/maintainers/release-sop.md` | Maintainer governance |
| `docs/maintainers/rotate-hypershift-ci-credentials.md` | **KEEP** | `docs/maintainers/rotate-hypershift-ci-credentials.md` | Already well-placed |
| `docs/demos/*` | **MOVE** | `docs/demos/*` | Rename to drop `demo-` prefix |
| `docs/plans/migrate-*.md` | **DELETE** | — | Completed migrations, no longer relevant |
| `docs/plans/shipwright-refactoring-plan.md` | **DELETE** | — | Completed, no longer relevant |
| `docs/plans/2026-02-15-session-metadata-*.md` | **DELETE** | — | Abandoned draft |
| `docs/plans/2025-02-05-*.md` | **CONVERT TO ADR** | `docs/adr/001-api-bearer-token-auth.md` | Strip impl details, preserve decision rationale |
| `docs/plans/2026-02-14-*.md` | **CONVERT TO ADR** | `docs/adr/002-agent-context-isolation.md` | Strip code details, preserve architectural decisions |
| `docs/plans/2026-02-24-*.md` | **MOVE** | `docs/proposals/` | Active proposal |
| `docs/plans/2026-03-08-*.md` | **CONVERT TO ADR** | `docs/adr/003-istio-shared-trust.md` | Active design decision |
| `docs/superpowers/` | **CONVERT TO ADR** | `docs/adr/004-agent-sandbox-workload-type.md` | Implemented decision, strip code details |
| `docs/env-import-feature-design.md` | **DELETE** | — | Implemented feature, no longer relevant |
| `docs/hypershift-auto-cleanup.md` | **MOVE** | `docs/development/local-dev-hypershift.md` | Merge into HyperShift dev guide |
| `docs/authbridge-combined-sidecar.md` | **DELETE** | — | Superseded by `docs/authbridge/` (PR #1476) |
| `docs/use-case-types.md` | **MOVE** | `docs/research/` | Taxonomy research |
| `docs/user-stories.md` | **MOVE + UPDATE** | `docs/concepts/` or **DELETE** | Fix broken link, evaluate value |
| `docs/architecture/agent-sandbox.md` | **MOVE** | `docs/concepts/sandboxing.md` | Concepts section |
| `docs/design-proposals/consolidated-*.md` | **MOVE** | `docs/proposals/` | Consolidate proposal dirs |
| `docs/agentic-runtime/` (rest) | **KEEP** | `docs/agentic-runtime/` | Active development area — review after sandbox ships |
| `docs/agents/otel-instrumentation.md` | **MOVE** | `docs/operator-guide/monitoring.md` | Merge into monitoring |
| `docs/research/openshell-mvp.md` | **KEEP + UPDATE** | `docs/research/openshell-mvp.md` | Fix dead links |
| `docs/diagrams/README.md` | **MOVE** | `docs/concepts/` | Merge diagrams into architecture |

---

## 6. New Docs Needed

| Proposed Path | Audience | Outline |
|---|---|---|
| `docs/getting-started/why-kagenti.md` | **User** | Value proposition and elevator pitch. What problems kagenti solves, how it differs from running agents directly, who it's for. Help new users understand *why* before *how*. (Volunteer: @esnible) |
| `docs/getting-started/quickstart.md` | **User** | Zero-to-running in 15 minutes. Covers: prerequisites, Kind cluster deploy via one command, access the UI, deploy the weather agent example, verify it works. No explanations — just steps. (Volunteer: @esnible) |
| `docs/getting-started/configuration.md` | **User** | Essential configuration for first deployment: how to set LLM API keys, choose a backend model, configure the UI URL, set admin credentials. Links to full config reference for advanced options. |
| `docs/concepts/agent-lifecycle.md` | **User** | Explains what happens when you "import" an agent: container image build (Shipwright), Deployment creation, sidecar injection (AuthBridge), service mesh enrollment (Istio), and readiness. Conceptual, not procedural. |
| `docs/concepts/protocols.md` | **User** | Explains A2A and MCP protocols at a conceptual level: what each does, when to use which, how kagenti implements them, and how they interact with auth. |
| `docs/operator-guide/config-reference.md` | **Operator** | Complete reference for all environment variables in `config.py` (~100 settings). Organized by category: server, auth, features, storage, observability. **Source:** auto-generate from kagenti-operator project. |
| `docs/operator-guide/helm-values-reference.md` | **Operator** | Structured reference for the Helm chart's `values.yaml`. Document every key, its type, default, and effect. **Source:** auto-generate from kagenti-operator project. |
| `docs/operator-guide/feature-flags.md` | **Operator** | Document all 7 feature flags: name, what it enables, how to activate (env var + Helm value), dependencies between flags, and current stability status. |
| `docs/operator-guide/monitoring.md` | **Operator** | Unified monitoring guide: Phoenix for LLM observability, Kiali for service mesh visualization, OTel instrumentation for agents. Consolidates `docs/kiali/` and `docs/agents/otel-instrumentation.md`. |
| `docs/reference/api.md` | **User** | API endpoint reference. Can be a maintained link to the live Swagger UI (`/api/docs`) plus a summary table of key endpoints, auth requirements, and rate limits. |
| `docs/adr/README.md` | **Contributor** | ADR process: when to write one, template (Context/Decision/Consequences), numbering scheme. ADRs capture the *why* behind architectural decisions — implementation details belong in code. |
| `docs/proposals/README.md` | **Contributor** | Proposal process: when to write one, template, review workflow, status lifecycle (Draft → Accepted → Implemented). Implemented proposals graduate to ADRs. |
| `docs/maintainers/upgrade-guide.md` | **Operator** | Version-to-version upgrade notes. Breaking changes, migration steps, deprecated features per release. Start with 0.5→0.6 as template. |
| `CHANGELOG.md` | **All** | Release history. Can initially be generated from GitHub Releases, then maintained manually per release. |

### Note on test documentation

E2E test specs and the test matrix are maintained as part of CI PRs (by @Ladas) and live alongside the tests themselves. Dedicated `testing.md` or `e2e-test-matrix.md` docs are intentionally excluded — they would go stale immediately as devs add tests without updating separate documentation. The test suite is self-documenting through markers, fixtures, and CI workflow definitions.

### Note on operator-generated docs

Several operator-guide files (`config-reference.md`, `helm-values-reference.md`) should be auto-generated from the kagenti-operator project rather than hand-maintained. This ensures they stay in sync with the actual CRDs and Helm chart values. The mechanism (CI job, make target, or script) is TBD.

---

## 7. Quick Wins (Immediate High-Impact Changes)

These 6 changes can be done immediately with maximum user impact:

### 1. Fix CLAUDE.md broken links and stale flag table
**Impact:** Stops every Claude Code user from hitting dead references.
**Effort:** 10 minutes.
- Remove references to `docs/skills/README.md`, `docs/ai-ops/README.md`
- Replace `docs/auth/keycloak-patterns.md` → `docs/authbridge/` (after PR #1476)
- Add the 4 missing feature flags to the table

### 2. Delete root-level noise files + completed plans
**Impact:** Cleaner repo, fewer misleading docs.
**Effort:** 5 minutes.
- Delete `AUTO-LABELING-FIX.md`, `TODO_CUSTOM_VISUALIZATIONS.md`
- Delete completed plans: `migrate-agent-crd-to-workloads.md`, `migrate-tool-mcpserver-to-workloads.md`, `shipwright-refactoring-plan.md`
- Convert any useful content to GitHub issues if needed

### 3. Rewrite getting-started for new users (@esnible volunteered)
**Impact:** The single most important missing doc. A new user today has no clear "start here" path — `docs/install.md` is 600+ lines mixing Kind, OpenShift, and advanced config. Users struggle to understand kagenti's value proposition.
**Effort:** 2-3 hours.
- Create `docs/getting-started/why-kagenti.md` — value proposition, what problems it solves
- Create `docs/getting-started/quickstart.md` — zero-to-running in 15 min
- Rewrite install flow from the admin perspective (not just "run this script")

### 4. Convert implemented proposals to ADRs
**Impact:** Preserves architectural decisions (the *why*) without cluttering the repo with stale implementation plans.
**Effort:** 1-2 hours.
- Create `docs/adr/` with README template
- Convert sandbox, auth, and Istio decisions — strip code details, keep Context/Decision/Consequences
- Delete raw implementation plans

### 5. Add security notice to `docs/identity-guide.md`
**Impact:** Prevents users from deploying with `admin`/`password` credentials in non-local environments.
**Effort:** 5 minutes.
- Add a callout box at the top: "All credentials in this guide are for LOCAL DEVELOPMENT ONLY."

### 6. Fix `README.md` "Langflow" reference
**Impact:** The main README is the project's front door. Referencing a tool not used in the project confuses new users.
**Effort:** 2 minutes.
- Replace "Langflow" with "Phoenix" (the actual observability tool).

---

## 8. Implementation Roadmap

| Phase | Scope | Owner | Effort |
|---|---|---|---|
| **Phase 0: AuthBridge** | Merge PR #1476 — lands `docs/authbridge/` which this reorg builds around | Reviewers | Days |
| **Phase 1: Cleanup** (Week 1) | Delete noise files + completed plans, fix broken links in CLAUDE.md | Anyone | 1 day |
| **Phase 2: ADRs** (Week 1-2) | Create `docs/adr/`, convert implemented proposals to decision records, delete raw plans | Maintainers | 1-2 days |
| **Phase 3: Getting Started** (Week 2-3) | Write `why-kagenti.md`, `quickstart.md`, rewrite install for admin perspective | @esnible | 3-5 days |
| **Phase 4: Restructure** (Week 3-4) | Create new directory structure, move files per migration table | Anyone | 2-3 days |
| **Phase 5: Operator Docs** (Week 4-6) | Auto-generate config-reference and helm-values from operator project, write feature-flags doc | Operator team | 1 week |
| **Phase 6: Polish** (Week 6-7) | Update `docs/README.md` index, add CODEOWNERS, create CHANGELOG, add cross-links | Anyone | 1 day |

---

## Appendix: Security-Sensitive Files Flagged

| File | Issue | Recommendation |
|------|-------|----------------|
| `docs/identity-guide.md` (lines 168-199, 533, 826) | Hardcoded `"password"`, `"admin"` for demo users | Add security callout banner |
| `kagenti/examples/identity/keycloak_token_exchange/demo_keycloak_config.py` | `admin_password = "admin"` | Add comment: "NEVER use in production" |
| `docs/install.md` (line 347) | `adminPassword: mypassword` in values example | Acceptable (clearly placeholder) |
| `docs/developer/kind.md` (line 404) | `OPENAI_API_KEY="sk-..."` | Acceptable (ellipsis placeholder) |

---

*Assisted-By: Claude Code*
