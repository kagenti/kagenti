---
name: orchestrate:plan
description: Brainstorm and create phased enhancement plan for a target repo - PR sizing, phase selection, task breakdown
---

```mermaid
flowchart TD
    START(["/orchestrate:plan"]) --> READ["Read scan report"]:::orch
    READ --> PRESENT["Present findings"]:::orch
    PRESENT --> BRAINSTORM["Brainstorm with developer"]:::orch
    BRAINSTORM --> SELECT["Select applicable phases"]:::orch
    SELECT --> SIZE["Size PRs (600-700 lines)"]:::orch
    SIZE --> WRITE["Write plan document"]:::orch
    WRITE --> DONE([Plan complete])

    classDef orch fill:#FF9800,stroke:#333,color:white
```

> Follow this diagram as the workflow.

# Orchestrate: Plan

Take the scan report and turn it into a concrete phased enhancement plan. This
is Phase 1 — interactive brainstorming with the developer, no PRs.

## When to Use

- After `orchestrate:scan` has produced a scan report
- Before starting any PR-producing phase

## Prerequisites

Scan report must exist:

```bash
cat /tmp/kagenti/orchestrate/<target>/scan-report.md
```

## Planning Process

### 1. Read the scan report

Review the Gap Summary and Recommended Phases sections.

### 2. Present findings to developer

Summarize the key gaps in plain language. Use AskUserQuestion to confirm
understanding and gather context about the repo's priorities.

### 3. Brainstorm which phases apply

Not all repos need all phases. Use AskUserQuestion to decide:

| Gap Found | Phase | Default |
|-----------|-------|---------|
| No pre-commit config | `orchestrate:precommit` | Always (foundation) |
| No/incomplete CI workflows | `orchestrate:ci` | Yes if missing |
| No/few tests (<5 test files) | `orchestrate:tests` | Yes if low coverage |
| No CODEOWNERS/dependabot/scorecard | `orchestrate:security` | Recommended |
| No `.claude/skills/` directory | `orchestrate:replicate` | Always (last phase) |

### 4. Determine phase order

Default order: precommit → ci → tests → security → replicate

Adjust if the developer has different priorities. Pre-commit should always be
first (it validates subsequent PRs). Replicate should always be last.

### 5. Size PRs

Target 600-700 lines per PR. For each phase:
- If estimated >700 lines: split into sub-PRs by concern
- If estimated <300 lines: merge with adjacent phase
- Skills pushed alongside each phase count toward the total

### 6. Write the plan document

## Plan Output

Save to `/tmp/kagenti/orchestrate/<target>/plan.md`:

```markdown
# Enhancement Plan: <target>

**Generated from scan:** YYYY-MM-DD
**Tech stack:** <language>
**Phases:** <count>

## Phase 2: Pre-commit (PR #1, ~NNN lines)
- [ ] Add .pre-commit-config.yaml
- [ ] Add linting config
- [ ] Create CLAUDE.md
- [ ] Create .claude/settings.json
- [ ] Add repo:commit skill

## Phase 3: CI (PR #2, ~NNN lines)
- [ ] Add lint workflow
- [ ] Add test workflow
- [ ] Add build workflow
- [ ] Add ci:status and rca:ci skills

## Phase 4: Tests (PR #3, ~NNN lines)
- [ ] Set up test framework
- [ ] Add test configuration
- [ ] Write initial tests for critical paths
- [ ] Add test:write and tdd:ci skills

## Phase 5: Security (PR #4, ~NNN lines)
- [ ] Create CODEOWNERS
- [ ] Add dependabot.yml
- [ ] Add scorecard workflow
- [ ] Audit .gitignore

## Phase 6: Replicate (PR #5)
- [ ] Copy orchestrate:* skills to target
- [ ] Adapt references
- [ ] Update CLAUDE.md
- [ ] Validate skills
```

## After Planning

Initialize phase tracking:

```bash
cat > /tmp/kagenti/orchestrate/<target>/phase-status.md << 'EOF'
# Phase Status: <target>

| Phase | Status | PR | Date |
|-------|--------|----|------|
| scan | complete | — | YYYY-MM-DD |
| plan | complete | — | YYYY-MM-DD |
| precommit | pending | | |
| ci | pending | | |
| tests | pending | | |
| security | pending | | |
| replicate | pending | | |
EOF
```

Then invoke the first applicable phase skill (usually `orchestrate:precommit`).

## Related Skills

- `orchestrate` — Parent router
- `orchestrate:scan` — Prerequisite: produces the scan report
- `orchestrate:precommit` — Usually the first PR-producing phase
