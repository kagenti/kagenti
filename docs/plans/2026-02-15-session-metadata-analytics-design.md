# Session Metadata Analytics - Design Document

**Date:** 2026-02-15
**Status:** Draft
**Branch:** `feature/session-metadata-skills`

## Problem

Claude Code sessions building PRs on kagenti/kagenti generate valuable metadata: token usage, model selection, skill invocations, subagent calls, CI iterations, problems faced. This data is currently lost when sessions end. Capturing it enables:

1. **Visibility** into agent-assisted development effort per PR/issue
2. **Dataset building** for fine-tuning agent skills (speed, token efficiency, acceptance rate)
3. **Portability** - same metadata format whether the agent runs locally or on OpenShift/Kagenti
4. **Optimization** - track which skills/workflows consume the most tokens and iterate

## Architecture

### Skill Category: `session/`

```
session/                           Claude Code session analytics
  session:post                   Post session stats to PR/issue comment
  session:summary                Update/create pinned summary comment
  session:extract                Extract analytics to CSV/MD/HTML for a date range
  session:dashboard              Generate local HTML dashboard from extracted data
```

### Single Entrypoint Script

`.claude/scripts/session-analytics.py` with `--phase` parameter:

| Phase | Description | Idempotent |
|-------|-------------|------------|
| `stats` | Parse JSONL, compute per-session stats, output JSON | Yes - same input produces same output |
| `mermaid` | Generate annotated Mermaid from stats + workflow templates | Yes - deterministic from stats |
| `comment` | Format and post/update GitHub comment on PR or issue | Yes - finds existing by session ID marker, updates |
| `summary` | Recalculate and post/update pinned summary comment | Yes - always recalculates from individual comments |
| `extract` | Extract from PR/issue comments to CSV + MD + HTML | Yes - overwrites output files |
| `dashboard` | Generate HTML dashboard with charts | Yes - regenerates from data |
| (no args) | Full pipeline: stats -> mermaid -> comment -> summary | Yes - each phase is idempotent |

Each phase can be run independently for debugging.

### Integration Points

- **TDD skills** (`tdd:ci`, `tdd:kind`, `tdd:hypershift`): invoke `session:post` at workflow completion
- **RCA skills** (`rca:ci`, `rca:hypershift`, `rca:kind`): invoke `session:post` at conclusion
- **GitHub analytics** (`github:last-week`): invoke `session:extract` for report enrichment

## Data Sources

### Claude Code Session JSONL

Located at `~/.claude/projects/<project-path>/<session-id>.jsonl`. Contains:

- **Per-message records** with `type: "assistant"` containing:
  - `message.model` - model used (e.g., `claude-opus-4-6`)
  - `message.usage` - token counts: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`
  - `message.content[]` - tool use records including `Skill` invocations and `Task` subagent launches
- **Subagent records** identified by `agentId` field and `isSidechain: true`
- **Timestamps** on all messages for duration calculation
- **Session metadata**: `sessionId`, `gitBranch`, `cwd`, `version`

### `/cost` Command Output

Used for verification against JSONL-parsed totals.

### GitHub API (via `gh` CLI)

- PR/issue metadata (number, title, author, status, labels, dates)
- CI workflow runs and results
- Review comments count
- Lines changed

## Data Model

### Per-Session Stats (JSON)

```json
{
  "session_id": "00b11888-7e0c-4fb4-bb39-32ea32e09b64",
  "session_id_short": "00b11888",
  "project": "kagenti/kagenti",
  "branch": "fix/keycloak-652",
  "target": {
    "type": "pr",
    "number": 652
  },
  "started_at": "2026-02-08T22:26:37Z",
  "ended_at": "2026-02-08T23:45:12Z",
  "duration_minutes": 78,
  "models": {
    "claude-opus-4-6": {
      "messages": 48,
      "input_tokens": 241558,
      "output_tokens": 835336,
      "cache_creation_tokens": 56722690,
      "cache_read_tokens": 458575867
    }
  },
  "total_tokens": {
    "input": 241558,
    "output": 835336,
    "cache_creation": 56722690,
    "cache_read": 458575867
  },
  "estimated_cost_usd": 12.45,
  "tools": {
    "Bash": 958,
    "Read": 328,
    "Edit": 343,
    "Grep": 110,
    "Glob": 31,
    "Write": 26,
    "Task": 9,
    "Skill": 3
  },
  "skills_invoked": [
    {
      "skill": "tdd:ci",
      "count": 2,
      "status": "pass",
      "tokens": {"input": 50000, "output": 120000}
    },
    {
      "skill": "rca:ci",
      "count": 1,
      "status": "pass",
      "tokens": {"input": 20000, "output": 45000}
    }
  ],
  "subagents": [
    {
      "id": "a3d04c8",
      "type": "Explore",
      "model": "haiku",
      "tokens": {"input": 5000, "output": 12000},
      "description": "Explore session metadata context"
    },
    {
      "id": "b7ef123",
      "type": "general-purpose",
      "model": "sonnet",
      "tokens": {"input": 8000, "output": 25000},
      "description": "Analyze CI failure logs"
    }
  ],
  "commits": [
    {"sha": "abc1234", "message": "Fix keycloak token refresh"},
    {"sha": "def5678", "message": "Add retry logic"}
  ],
  "problems_faced": [
    {
      "description": "CI lint failure on line 42",
      "resolved": true,
      "iterations": 2
    }
  ],
  "workflow_edges": {
    "tdd": {
      "RCACI->TDDCI": 1,
      "TDDCI->HS": 2,
      "HS->REVIEWS": 1
    },
    "ci": {
      "STATUS->RESULT": 3,
      "RESULT->RCACI": 2
    }
  }
}
```

## PR/Issue Comment Templates

### Per-Session Comment

Posted by `session:post`. Updated if same session posts again.

```markdown
## Claude Code Session Report

**TL;DR:** Session `00b11888` | opus-4-6 | 1h 18m | $12.45 | 2 commits | tdd:ci, rca:ci

**Session:** `00b11888` | **Branch:** `fix/keycloak-652` | **Duration:** 1h 18m

### Token Usage

| Model | Input | Output | Cache Create | Cache Read | Est. Cost |
|-------|-------|--------|-------------|------------|-----------|
| claude-opus-4-6 | 241,558 | 835,336 | 56.7M | 458.6M | $12.45 |
| **Total** | **241,558** | **835,336** | **56.7M** | **458.6M** | **$12.45** |

### Subagents

| ID | Type | Model | Input | Output |
|----|------|-------|-------|--------|
| a3d04c8 | Explore | haiku | 5,000 | 12,000 |
| b7ef123 | general-purpose | sonnet | 8,000 | 25,000 |

### Skills & Tools

| Skill | Invocations | Status |
|-------|-------------|--------|
| tdd:ci | 2 | pass |
| rca:ci | 1 | pass |

<details><summary>Tool Usage</summary>

| Tool | Count |
|------|-------|
| Bash | 958 |
| Edit | 343 |
| Read | 328 |
| Grep | 110 |
| Glob | 31 |
| Write | 26 |
| Task | 9 |
| Skill | 3 |

</details>

### TDD Workflow

(Mermaid diagram with green/red/grey edges and traversal counters)

### Problems Faced

| Problem | Resolved | Iterations |
|---------|----------|------------|
| CI lint failure on line 42 | yes | 2 |

### Commits

- `abc1234` - Fix keycloak token refresh
- `def5678` - Add retry logic

<details><summary>Session Data (JSON)</summary>

(Full JSON stats block - machine-parseable for extraction)

</details>
```

### Pinned Summary Comment

Posted by `session:summary`. Always recalculated from individual session comments.

```markdown
## Claude Code PR Summary

**TL;DR:** 3 sessions | $34.21 total | 8 commits | merged

**Sessions:** 3 | **Total Cost:** $34.21 | **Commits:** 8

### Aggregate Token Usage

| Model | Input | Output | Cache Create | Cache Read | Est. Cost |
|-------|-------|--------|-------------|------------|-----------|
| claude-opus-4-6 | 723K | 2.5M | 170M | 1.4B | $34.21 |

### Session History

| # | Session | Duration | Cost | Skills | Commits | Status |
|---|---------|----------|------|--------|---------|--------|
| 1 | `00b11888` | 1h 18m | $12.45 | tdd:ci, rca:ci | 2 | done |
| 2 | `a3f92bc1` | 45m | $8.32 | tdd:ci | 3 | done |
| 3 | `f7e01d4a` | 2h 05m | $13.44 | tdd:hypershift | 3 | done |

### Totals Verification

- Sum of session costs: $12.45 + $8.32 + $13.44 = **$34.21**
- Sum of session commits: 2 + 3 + 3 = **8**

<details><summary>Summary Data (JSON)</summary>

(Aggregated JSON - machine-parseable)

</details>
```

### Reliability Guarantees

1. **Pinned summary always recalculates from individual comments** - never incremental updates
2. **Each session comment contains full JSON** in a collapsible block - single source of truth
3. **Comment identification** uses markers: `<!-- SESSION:00b11888 -->` for per-session, `<!-- SESSION_SUMMARY -->` for pinned
4. **Idempotent updates** - running `session:post` twice for the same session updates the existing comment
5. **Sum verification** - the summary comment includes explicit sum calculations that must match

## Mermaid Workflow Diagrams

### Approach

Reuse the pattern from `tdd-debug-diagram.py`:

1. Start from the workflow Mermaid templates defined in each skill's `SKILL.md`
2. For each skill that has a workflow diagram and was invoked during the session:
   - Parse the base Mermaid template
   - Color edges: green = traversed successfully, red = error path, grey = not traversed
   - Add traversal counters on edges (e.g., `|"CI green (2x)"|`)
   - Include the annotated diagram in the session comment

### Diagram Sources

| Skill | Workflow Template |
|-------|-------------------|
| tdd | `.claude/skills/tdd/SKILL.md` (TDD Workflow section) |
| rca | `.claude/skills/rca/SKILL.md` (RCA Workflow section) |
| ci | `.claude/skills/ci/SKILL.md` (CI Workflow section) |
| test | `.claude/skills/test/SKILL.md` (Test Workflow section) |

The script extracts the mermaid code block from each skill's SKILL.md, applies the coloring based on `workflow_edges` from session stats, and embeds the result.

### Color Scheme

| Color | Meaning | Hex |
|-------|---------|-----|
| Green | Traversed successfully | `#4CAF50` |
| Red | Error/failure path traversed | `#F44336` |
| Grey | Not traversed (unused) | `#9E9E9E` |

Nodes: green fill if the skill was invoked and completed, grey if not invoked.
Edges: colored per traversal status, with `Nx` counter labels.

## CSV Extraction

### Command

```bash
python3 .claude/scripts/session-analytics.py \
  --phase extract \
  --repo kagenti/kagenti \
  --from 2026-01-01 --to 2026-02-15 \
  --output-dir /tmp/kagenti/session/
```

### Outputs

Three files in the output directory:

1. **`analytics.csv`** - Full dataset without diagrams
2. **`analytics.md`** - Markdown report with tables and summary statistics
3. **`dashboard.html`** - Interactive HTML dashboard with Chart.js charts

### CSV Columns (Extended Set)

| Column | Source | Description |
|--------|--------|-------------|
| `pr_number` | GH API | PR or issue number |
| `target_type` | GH API | `pr` or `issue` |
| `pr_title` | GH API | Title |
| `pr_author` | GH API | Author login |
| `pr_status` | GH API | open/merged/closed |
| `session_id` | Comment JSON | Full session UUID |
| `session_started` | Comment JSON | ISO timestamp |
| `session_duration_min` | Comment JSON | Duration in minutes |
| `models_used` | Comment JSON | Comma-separated model list |
| `total_input_tokens` | Comment JSON | Input tokens |
| `total_output_tokens` | Comment JSON | Output tokens |
| `total_cache_create` | Comment JSON | Cache creation tokens |
| `total_cache_read` | Comment JSON | Cache read tokens |
| `estimated_cost_usd` | Comment JSON | Estimated cost |
| `commits_count` | Comment JSON | Number of commits |
| `commit_shas` | Comment JSON | Semicolon-separated SHAs |
| `ci_runs` | GH API | Number of CI workflow runs |
| `ci_pass_rate` | GH API | Percentage of passing runs |
| `skills_used` | Comment JSON | Comma-separated skill list |
| `per_skill_tokens` | Comment JSON | JSON string: skill -> {in, out} |
| `subagent_count` | Comment JSON | Number of subagents |
| `per_subagent_tokens` | Comment JSON | JSON string: type -> {in, out} |
| `problems_count` | Comment JSON | Problems encountered |
| `problems_resolved` | Comment JSON | Problems resolved |
| `review_comments` | GH API | Number of review comments |
| `lines_added` | GH API | Lines added in PR |
| `lines_removed` | GH API | Lines removed in PR |
| `time_to_merge_hours` | GH API | Hours from creation to merge |
| `acceptance_status` | GH API | merged/closed/open |

### Extraction Logic

1. `gh pr list` / `gh issue list` with date range filter
2. For each PR/issue, fetch comments via `gh api`
3. Find comments with `<!-- SESSION:... -->` markers
4. Parse the JSON from the collapsible `Session Data (JSON)` block
5. Merge with PR/issue metadata from GH API
6. Output CSV, MD report, and HTML dashboard

### Markdown Report

```markdown
# Claude Code Analytics Report

**Period:** 2026-01-01 to 2026-02-15
**Repository:** kagenti/kagenti

## Summary

| Metric | Value |
|--------|-------|
| PRs with session data | 42 |
| Issues with session data | 8 |
| Total sessions | 67 |
| Total cost | $523.45 |
| Total commits | 234 |
| Average cost per PR | $12.46 |
| PR acceptance rate | 92% |
| Average time to merge | 4.2h |

## Per-PR Breakdown

(table with key metrics per PR)

## Model Usage Distribution

(table showing token/cost breakdown by model)

## Skill Effectiveness

(table showing which skills were used most and their token costs)
```

### HTML Dashboard

Interactive dashboard at `/tmp/kagenti/session/dashboard.html`:

- Token usage over time (line chart)
- Cost per PR (bar chart)
- Skills usage frequency (pie chart)
- Acceptance rate trend (line chart)
- Model distribution (doughnut chart)
- Generated with Chart.js (CDN) for interactivity

## Issue Support

The same comment templates and extraction work for GitHub issues, enabling tracking of research/investigation effort:

- `session:post --target issue --number 123` posts to an issue
- `session:summary --target issue --number 123` updates the pinned summary on an issue
- CSV extraction includes `target_type` column (`pr` or `issue`)
- Mermaid diagrams still work (e.g., RCA workflows on issues)

## File Layout

```
.claude/
  scripts/
    session-analytics.py          # Single entrypoint (all phases)
  skills/
    session/
      SKILL.md                    # Router skill
      post/
        SKILL.md                  # Post session stats to PR/issue
      summary/
        SKILL.md                  # Update pinned summary comment
      extract/
        SKILL.md                  # Extract to CSV/MD/HTML
      dashboard/
        SKILL.md                  # Generate HTML dashboard
```

## Future Considerations

- **OpenShift-hosted agents**: Same comment format, different session source (OTel traces instead of local JSONL)
- **OTel integration**: Session stats as span attributes for GenAI observability
- **Fine-tuning dataset**: CSV output can feed skill optimization pipelines
- **Cross-repo**: Support extracting from multiple repositories
