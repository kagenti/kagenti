# Repo Orchestration & Onboarding — Design Document

**Date:** 2026-02-14
**Branch:** `feat/repo-orchestration-skills`
**Status:** Draft

## Problem

The kagenti org has 13+ repositories. Only kagenti/kagenti has Claude Code skills,
CI hardening, and agentic development workflows. Other repos lack:
- Pre-commit hooks and linting
- CI workflows (or have minimal ones)
- Test infrastructure
- Security hardening (CODEOWNERS, dependency scanning, branch protection)
- Claude Code skills for autonomous development

We need a **replicable system** that brings any repo up to agentic quality
standards through phased, reviewable PRs.

## Architecture

### Two-Layer Model

**Layer 1: `orchestrate`** — Generic repo enhancement. Works on any repository.
Self-replicating: the orchestrate skills themselves get bootstrapped into the
target repo, enabling it to orchestrate its own related repos.

**Layer 2: `onboard`** — Kagenti-specific integration. Connects an orchestrated
repo to kagenti/kagenti as the hub. Not required for independent repos.

```
kagenti/kagenti/                          # Hub / Orchestrator
├── .claude/skills/
│   ├── orchestrate/SKILL.md              # Router skill
│   ├── orchestrate:scan/SKILL.md         # Phase 0: Assess target repo
│   ├── orchestrate:plan/SKILL.md         # Phase 1: Brainstorm + plan
│   ├── orchestrate:precommit/SKILL.md    # Phase 2: Pre-commit hooks
│   ├── orchestrate:ci/SKILL.md           # Phase 3: CI workflows
│   ├── orchestrate:tests/SKILL.md        # Phase 4: Test infrastructure
│   ├── orchestrate:security/SKILL.md     # Phase 5: Security hardening
│   ├── orchestrate:replicate/SKILL.md    # Phase 6: Bootstrap skills into target
│   │
│   ├── onboard/SKILL.md                  # Kagenti-specific router
│   ├── onboard:link/SKILL.md             # Clone into .repos/, configure
│   └── onboard:standards/SKILL.md        # Apply kagenti conventions
│
├── .repos/                               # Cloned target repos (gitignored)
│   ├── kagenti-operator/
│   ├── hypershift-automation/
│   └── agentic-control-plane/
└── .gitignore                            # .repos/
```

### Self-Replication Chain

```
kagenti/kagenti  ──orchestrate──▶  kagenti-operator
                 ──onboard──▶     (linked to kagenti hub)

kagenti-operator ──orchestrate──▶  other-repo
                                   (independent, works on its own)
```

After `orchestrate:replicate`, the target repo has its own orchestrate skills and
can enhance its related repos without kagenti/kagenti involvement.

### Cross-Repo Skill Discovery

Claude Code discovers skills from nested `.claude/skills/` directories on-demand
when reading files in subdirectories. This means:

- **Orchestration skills**: Always loaded (CWD is kagenti/kagenti)
- **Target repo skills**: Discovered when Claude reads/writes files in `.repos/<target>/`
- **No duplication**: Skills live in their own repo, not copied to the hub
- **No `--add-dir` needed**: Nesting handles discovery automatically

The `.repos/` directory is gitignored. Each entry is a regular `git clone` (not
a git worktree, since worktrees only work within the same repository).

## Orchestration Phases

### Phase 0: Scan (`orchestrate:scan`)

Analyze the target repo to determine its current state:

```
Input:  .repos/<target>/
Output: /tmp/kagenti/orchestrate/<target>/scan-report.md
```

**Checks:**
- Language/framework detection (go.mod, pyproject.toml, package.json, etc.)
- CI status: existing workflows, what they cover, what's missing
- Test status: test directories, frameworks, coverage
- Security: CODEOWNERS, .gitignore secrets patterns, dependency scanning
- Claude Code: .claude/ directory, skills, settings, CLAUDE.md
- Pre-commit: hooks configuration, linting tools
- Git: branch protection, signed commits, conventional commits

**Output:** A structured report with current state and gap analysis.

### Phase 1: Plan (`orchestrate:plan`)

Brainstorm with the developer on what the repo needs:

```
Input:  scan-report.md + developer context
Output: /tmp/kagenti/orchestrate/<target>/plan.md
```

**Process:**
1. Present scan findings to the developer
2. Brainstorm which phases apply (not all repos need all phases)
3. Estimate PR sizes — target 600-700 lines per PR
4. If a phase would exceed 700 lines, split it into sub-PRs
5. Determine phase order (usually: precommit → ci → tests → security)
6. Generate the plan document with specific tasks per phase

**Plan format:**
```markdown
## Phase 2: Pre-commit (PR #1, ~650 lines)
- [ ] Add .pre-commit-config.yaml with hooks for: X, Y, Z
- [ ] Add linting config (pyproject.toml / .golangci.yml / .eslintrc)
- [ ] Add CLAUDE.md with repo overview
- [ ] Add .claude/settings.json with auto-approve patterns

## Phase 3: CI (PR #2, ~600 lines)
- [ ] Add lint workflow
- [ ] Add test workflow
- [ ] Add build workflow
...
```

### Phase 2: Pre-commit (`orchestrate:precommit`)

First PR — establishes code quality baseline:

**Contents (target ~600-700 lines):**
- `.pre-commit-config.yaml` — language-appropriate hooks
- Linting config — `.golangci.yml` / `pyproject.toml [tool.ruff]` / `.eslintrc`
- `Makefile` — `make lint`, `make fmt` targets (if not present)
- `CLAUDE.md` — repo overview, key commands, structure
- `.claude/settings.json` — auto-approve patterns for read-only commands
- Skills pushed alongside: initial repo-specific skills (e.g., `repo:commit`)

**PR includes skills:** Each phase pushes relevant `.claude/skills/` alongside
the functional changes. Pre-commit phase includes foundational skills.

### Phase 3: CI (`orchestrate:ci`)

Second PR — automated checks on every push/PR:

**Contents (target ~600-700 lines):**
- `.github/workflows/lint.yml` — linting on PR
- `.github/workflows/test.yml` — test suite on PR
- `.github/workflows/build.yml` — build verification
- `.github/workflows/security.yml` — dependency scanning (if not in Phase 5)
- Skills pushed alongside: `ci:status`, `ci:monitoring`, `rca:ci`

**Adapts to tech stack:**
- Go repos: `golangci-lint`, `go test`, `go build`
- Python repos: `ruff`, `pytest`, `uv build`
- Node repos: `eslint`, `jest`/`vitest`, `npm run build`
- Ansible repos: `ansible-lint`, `yamllint`, `molecule test`

### Phase 4: Tests (`orchestrate:tests`)

Third PR — test infrastructure and initial test coverage:

**Contents (target ~600-700 lines):**
- Test framework setup (if not present)
- Test configuration (conftest.py, test helpers, fixtures)
- Initial tests for critical paths (identified during scan)
- CI integration (test workflow if not added in Phase 3)
- Skills pushed alongside: `test:write`, `test:run`, `tdd:ci`

**Strategy:** Focus on the most impactful tests first — API endpoints, core
business logic, integration points. Don't aim for 100% coverage in one PR.

### Phase 5: Security (`orchestrate:security`)

Fourth PR — security hardening:

**Contents (target ~600-700 lines):**
- `CODEOWNERS` — define code ownership
- `.github/dependabot.yml` — automated dependency updates
- `.github/workflows/scorecard.yml` — OpenSSF Scorecard
- `.gitignore` audit — ensure secrets patterns are excluded
- Branch protection recommendations (documented, not auto-applied)
- Skills pushed alongside: security-related skills

### Phase 6: Replicate (`orchestrate:replicate`)

Fifth PR — make the target repo self-sufficient:

**Contents:**
- Copy `orchestrate:*` skills into target repo's `.claude/skills/`
- Adapt skill references to the target repo's context
- Update target repo's CLAUDE.md to reference orchestration skills
- The target repo can now orchestrate its own related repos

**This is what makes it fractal.** After this phase, the target repo doesn't
depend on kagenti/kagenti to enhance other repos.

## Onboarding (Kagenti-Specific)

### `onboard:link`

Connect an orchestrated repo to the kagenti/kagenti hub:

1. Clone target repo into `.repos/<target>/`
2. Add entry to `.repos/README.md` (inventory of connected repos)
3. Verify skill discovery works (Claude can find target's skills)

### `onboard:standards`

Apply kagenti-specific conventions:

1. Commit message format (emoji prefixes, sign-off)
2. PR template matching kagenti conventions
3. Issue templates
4. Kagenti-specific CI checks (if applicable)
5. Cross-reference skills (link to kagenti skills where relevant)

## PR Sizing Strategy

**Target: 600-700 lines per PR.** This is large enough to be meaningful but
small enough for effective review.

**Splitting rules:**
- If a phase naturally exceeds 700 lines, split by concern:
  - CI phase: split into lint + test + build workflows
  - Test phase: split into framework setup + initial tests
- If a phase is under 300 lines, consider merging with the next phase
- Skills count toward the line total (they're part of the PR)

**Each PR is independently reviewable and mergeable.** No PR depends on a
previous one being merged first (though the intended order is sequential).

## Target Repos (Initial Candidates)

| Repo | Priority | Key Gaps |
|------|----------|----------|
| kagenti-operator | High | No .claude/, has CI but incomplete |
| hypershift-automation | High | No .claude/, no CI, no tests |
| agentic-control-plane | Medium | No .claude/, no CI |
| kagenti-phoenix-integration | Medium | Has .claude/, has CI, needs tests |
| kagenti-openshift-ci | Medium | Has .claude/, has CI, needs tests |
| kagenti-kiali-integration | Low | No .claude/, minimal |
| kagenti-llama-demo | Low | No .claude/, demo repo |

## Developer Workflow

```bash
# 1. Start in kagenti/kagenti
cd /path/to/kagenti/kagenti

# 2. Clone target repo
git clone git@github.com:kagenti/kagenti-operator.git .repos/kagenti-operator

# 3. Start Claude Code (orchestration skills auto-loaded)
claude

# 4. In Claude: invoke orchestrate:scan
#    → scans .repos/kagenti-operator/
#    → produces scan report

# 5. In Claude: invoke orchestrate:plan
#    → brainstorms with developer
#    → produces phased plan

# 6. In Claude: invoke orchestrate:precommit
#    → creates branch in .repos/kagenti-operator/
#    → implements pre-commit hooks + linting + initial skills
#    → opens PR #1 (~600 lines)

# 7. Repeat for each phase...
```

## Open Questions

1. **Skill versioning**: When orchestrate skills evolve in kagenti/kagenti, how
   do replicated copies in target repos stay in sync? Options:
   - Manual: developer re-runs `orchestrate:replicate`
   - Git submodule for skills (complex)
   - Accept divergence (each repo evolves independently)

2. **Cross-repo CI**: Should orchestrated repos report status back to the hub?
   Or is repo-level CI sufficient?

3. **Naming the concept**: "Orchestrate" for the generic capability,
   "onboard" for kagenti-specific. Are these the right terms long-term?
