# Session Metadata Analytics - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build skills and tooling to capture Claude Code session metadata (tokens, models, skills, subagents, problems) and post structured comments to PRs/issues with annotated Mermaid workflow diagrams, plus CSV/MD/HTML extraction for analytics.

**Architecture:** Single Python script (`.claude/scripts/session-analytics.py`) with `--phase` parameter for idempotent pipeline stages. Four Claude Code skills (`session:post`, `session:summary`, `session:extract`, `session:dashboard`) orchestrate the script. Integration hooks added to existing TDD/RCA/CI skills.

**Tech Stack:** Python 3.11+, `gh` CLI for GitHub API, Mermaid syntax for workflow diagrams, Chart.js for HTML dashboard.

**Design doc:** `docs/plans/2026-02-15-session-metadata-analytics-design.md`

---

### Task 1: Scaffold session-analytics.py with CLI argument parsing

**Files:**
- Create: `.claude/scripts/session-analytics.py`

**Step 1: Create the script with argument parsing**

```python
#!/usr/bin/env python3
"""Session analytics for Claude Code - parse JSONL, generate stats, post to GitHub.

Single entrypoint with --phase parameter for idempotent pipeline stages:
  stats    - Parse JSONL, compute per-session stats, output JSON
  mermaid  - Generate annotated Mermaid from stats + workflow templates
  comment  - Format and post/update GitHub comment on PR or issue
  summary  - Recalculate and post/update pinned summary comment
  extract  - Extract from PR/issue comments to CSV + MD + HTML
  dashboard - Generate HTML dashboard with charts
  (no phase) - Full pipeline: stats -> mermaid -> comment -> summary

Usage:
    python3 .claude/scripts/session-analytics.py --phase stats \
        --session-id <uuid> --project-dir <path>

    python3 .claude/scripts/session-analytics.py --phase comment \
        --stats-file /tmp/kagenti/session/stats.json \
        --target pr --number 652 --repo kagenti/kagenti

    python3 .claude/scripts/session-analytics.py --phase extract \
        --repo kagenti/kagenti --from 2026-01-01 --to 2026-02-15 \
        --output-dir /tmp/kagenti/session/
"""

import argparse
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Claude Code session analytics")
    p.add_argument(
        "--phase",
        choices=["stats", "mermaid", "comment", "summary", "extract", "dashboard"],
        default=None,
        help="Pipeline phase to run. If omitted, runs full pipeline.",
    )

    # Stats phase args
    p.add_argument("--session-id", help="Session UUID to analyze")
    p.add_argument(
        "--project-dir",
        help="Claude Code project dir (default: auto-detect from cwd)",
    )
    p.add_argument(
        "--stats-file",
        help="Path to stats JSON file (input for mermaid/comment, output for stats)",
    )

    # Mermaid phase args
    p.add_argument(
        "--skills-dir",
        help="Path to .claude/skills/ directory for workflow templates",
    )

    # Comment/summary phase args
    p.add_argument(
        "--target",
        choices=["pr", "issue"],
        help="GitHub target type",
    )
    p.add_argument("--number", type=int, help="PR or issue number")
    p.add_argument("--repo", help="GitHub repo (owner/name)")

    # Extract phase args
    p.add_argument("--from-date", dest="from_date", help="Start date (YYYY-MM-DD)")
    p.add_argument("--to-date", dest="to_date", help="End date (YYYY-MM-DD)")
    p.add_argument(
        "--output-dir",
        help="Output directory for CSV/MD/HTML",
        default="/tmp/kagenti/session/",
    )

    return p.parse_args()


def main():
    args = parse_args()

    if args.phase == "stats":
        from session_phases import run_stats
        run_stats(args)
    elif args.phase == "mermaid":
        from session_phases import run_mermaid
        run_mermaid(args)
    elif args.phase == "comment":
        from session_phases import run_comment
        run_comment(args)
    elif args.phase == "summary":
        from session_phases import run_summary
        run_summary(args)
    elif args.phase == "extract":
        from session_phases import run_extract
        run_extract(args)
    elif args.phase == "dashboard":
        from session_phases import run_dashboard
        run_dashboard(args)
    elif args.phase is None:
        # Full pipeline
        from session_phases import run_full_pipeline
        run_full_pipeline(args)
    else:
        print(f"ERROR: Unknown phase '{args.phase}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2: Make executable and verify it parses args**

Run: `chmod +x .claude/scripts/session-analytics.py`
Run: `python3 .claude/scripts/session-analytics.py --help`
Expected: Help text with all arguments listed.

**Step 3: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: scaffold session-analytics.py with CLI argument parsing"
```

---

### Task 2: Implement --phase stats (JSONL parsing)

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

This is the core parser that reads Claude Code JSONL session files and produces a structured JSON stats output.

**Step 1: Write test for stats parsing**

Create a test JSONL fixture and a test script:

```python
# At the bottom of session-analytics.py, or as a separate test
# For now, add a self-test mode: --self-test
```

Add `--self-test` flag that creates a minimal JSONL fixture in /tmp and runs the parser against it.

**Step 2: Implement the stats phase**

Add these functions to `session-analytics.py` (not as imports, keep it single-file):

```python
import json
import os
import glob
import re
from datetime import datetime, timezone
from collections import Counter, defaultdict


# Pricing per 1M tokens (approximate, for cost estimation)
MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_create": 18.75, "cache_read": 1.50},
    "claude-opus-4-5-20251101": {"input": 15.0, "output": 75.0, "cache_create": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0, "cache_create": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_create": 1.0, "cache_read": 0.08},
}

# Default pricing for unknown models
DEFAULT_PRICING = {"input": 3.0, "output": 15.0, "cache_create": 3.75, "cache_read": 0.30}


def find_session_file(session_id, project_dir=None):
    """Find the JSONL file for a session, auto-detecting project dir if needed."""
    if project_dir:
        path = os.path.join(project_dir, f"{session_id}.jsonl")
        if os.path.exists(path):
            return path
        return None

    # Auto-detect from ~/.claude/projects/
    claude_dir = os.path.expanduser("~/.claude/projects/")
    for project in os.listdir(claude_dir):
        path = os.path.join(claude_dir, project, f"{session_id}.jsonl")
        if os.path.exists(path):
            return path
    return None


def estimate_cost(model, usage):
    """Estimate cost in USD for token usage with a given model."""
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    cost = 0.0
    cost += (usage.get("input_tokens", 0) / 1_000_000) * pricing["input"]
    cost += (usage.get("output_tokens", 0) / 1_000_000) * pricing["output"]
    cost += (usage.get("cache_creation_input_tokens", 0) / 1_000_000) * pricing["cache_create"]
    cost += (usage.get("cache_read_input_tokens", 0) / 1_000_000) * pricing["cache_read"]
    return cost


def parse_session_jsonl(filepath):
    """Parse a Claude Code session JSONL file and extract stats."""
    models = defaultdict(lambda: {
        "messages": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
    })
    tools = Counter()
    skills_invoked = defaultdict(lambda: {"count": 0, "status": "unknown"})
    subagents = {}
    commits = []
    problems = []
    timestamps = []
    session_id = None
    branch = None
    workflow_edges = defaultdict(dict)

    with open(filepath) as f:
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract session metadata
            if not session_id and data.get("sessionId"):
                session_id = data["sessionId"]
            if not branch and data.get("gitBranch"):
                branch = data["gitBranch"]

            # Track timestamps
            ts = data.get("timestamp")
            if ts:
                timestamps.append(ts)

            # Track subagents
            agent_id = data.get("agentId")
            if agent_id and agent_id not in subagents:
                subagents[agent_id] = {
                    "id": agent_id,
                    "type": "unknown",
                    "model": "unknown",
                    "tokens": {"input": 0, "output": 0},
                    "description": "",
                }

            # Process assistant messages
            if data.get("type") == "assistant" and "message" in data:
                msg = data["message"]
                model = msg.get("model", "unknown")
                usage = msg.get("usage", {})

                # Aggregate model usage
                m = models[model]
                m["messages"] += 1
                m["input_tokens"] += usage.get("input_tokens", 0)
                m["output_tokens"] += usage.get("output_tokens", 0)
                m["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0)
                m["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)

                # Track subagent model/tokens
                if agent_id and agent_id in subagents:
                    subagents[agent_id]["model"] = model
                    subagents[agent_id]["tokens"]["input"] += usage.get("input_tokens", 0)
                    subagents[agent_id]["tokens"]["output"] += usage.get("output_tokens", 0)

                # Process tool uses in content
                for content in msg.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") != "tool_use":
                        continue

                    tool_name = content.get("name", "unknown")
                    tools[tool_name] += 1

                    inp = content.get("input", {})

                    # Track Skill invocations
                    if tool_name == "Skill":
                        skill_name = inp.get("skill", "unknown")
                        skills_invoked[skill_name]["count"] += 1

                    # Track Task (subagent) launches
                    if tool_name == "Task":
                        sub_type = inp.get("subagent_type", "unknown")
                        desc = inp.get("description", "")
                        # Try to match to agent ID from subsequent messages
                        # For now, record the launch
                        subagent_key = f"task-{len(subagents)}"
                        subagents[subagent_key] = {
                            "id": subagent_key,
                            "type": sub_type,
                            "model": inp.get("model", "inherit"),
                            "tokens": {"input": 0, "output": 0},
                            "description": desc,
                        }

                    # Track git commits in Bash calls
                    if tool_name == "Bash":
                        cmd = inp.get("command", "")
                        if "git commit" in cmd:
                            # Extract commit message
                            msg_match = re.search(r'-m\s+["\'](.+?)["\']', cmd)
                            if msg_match:
                                commits.append({
                                    "message": msg_match.group(1)[:100],
                                })

    # Compute totals
    total_tokens = {
        "input": sum(m["input_tokens"] for m in models.values()),
        "output": sum(m["output_tokens"] for m in models.values()),
        "cache_creation": sum(m["cache_creation_tokens"] for m in models.values()),
        "cache_read": sum(m["cache_read_tokens"] for m in models.values()),
    }

    # Estimate total cost
    total_cost = sum(
        estimate_cost(model, {
            "input_tokens": m["input_tokens"],
            "output_tokens": m["output_tokens"],
            "cache_creation_input_tokens": m["cache_creation_tokens"],
            "cache_read_input_tokens": m["cache_read_tokens"],
        })
        for model, m in models.items()
    )

    # Compute duration
    started_at = min(timestamps) if timestamps else None
    ended_at = max(timestamps) if timestamps else None
    duration_minutes = 0
    if started_at and ended_at:
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            duration_minutes = int((end - start).total_seconds() / 60)
        except (ValueError, TypeError):
            pass

    return {
        "session_id": session_id or os.path.basename(filepath).replace(".jsonl", ""),
        "session_id_short": (session_id or "unknown")[:8],
        "branch": branch,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_minutes": duration_minutes,
        "models": dict(models),
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(total_cost, 2),
        "tools": dict(tools),
        "skills_invoked": [
            {"skill": k, "count": v["count"], "status": v["status"]}
            for k, v in skills_invoked.items()
        ],
        "subagents": list(subagents.values()),
        "commits": commits,
        "problems_faced": problems,
        "workflow_edges": dict(workflow_edges),
    }


def run_stats(args):
    """Run the stats phase: parse JSONL and output JSON stats."""
    if not args.session_id:
        # Try to detect current session
        print("ERROR: --session-id is required for stats phase", file=sys.stderr)
        sys.exit(1)

    filepath = find_session_file(args.session_id, args.project_dir)
    if not filepath:
        print(f"ERROR: Session file not found for {args.session_id}", file=sys.stderr)
        sys.exit(1)

    stats = parse_session_jsonl(filepath)

    # Add target info if provided
    if args.target and args.number:
        stats["target"] = {"type": args.target, "number": args.number}
    if args.repo:
        stats["project"] = args.repo

    # Output
    output_path = args.stats_file or f"/tmp/kagenti/session/{args.session_id[:8]}-stats.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Stats: {output_path}")
    print(f"Session: {stats['session_id_short']} | Duration: {stats['duration_minutes']}m | Cost: ${stats['estimated_cost_usd']}")
    print(f"Models: {', '.join(stats['models'].keys())}")
    print(f"Tools: {sum(stats['tools'].values())} calls across {len(stats['tools'])} tools")
    if stats['skills_invoked']:
        print(f"Skills: {', '.join(s['skill'] for s in stats['skills_invoked'])}")
```

**Step 3: Test with a real session**

Run: `python3 .claude/scripts/session-analytics.py --phase stats --session-id 00b11888-7e0c-4fb4-bb39-32ea32e09b64`
Expected: JSON stats output written to `/tmp/kagenti/session/00b11888-stats.json`

**Step 4: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement --phase stats for JSONL session parsing"
```

---

### Task 3: Implement --phase mermaid (workflow diagram annotation)

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

Reuse the pattern from `tdd-debug-diagram.py` to annotate workflow Mermaid diagrams based on session stats.

**Step 1: Implement mermaid phase**

Add these functions to `session-analytics.py`:

```python
def extract_mermaid_from_skill(skill_path):
    """Extract the first mermaid code block from a SKILL.md file."""
    if not os.path.exists(skill_path):
        return None
    with open(skill_path) as f:
        content = f.read()
    match = re.search(r"```mermaid\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def find_skill_workflow(skill_name, skills_dir):
    """Find the workflow mermaid template for a skill."""
    # Try exact skill path first: skill_name -> skills_dir/skill_name/SKILL.md
    # Handle colon notation: "tdd:ci" -> "tdd:ci/SKILL.md"
    skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")
    if os.path.exists(skill_path):
        return extract_mermaid_from_skill(skill_path)

    # Try parent skill (e.g., "tdd:ci" -> "tdd/SKILL.md")
    parent = skill_name.split(":")[0]
    parent_path = os.path.join(skills_dir, parent, "SKILL.md")
    if os.path.exists(parent_path):
        return extract_mermaid_from_skill(parent_path)

    return None


# Reuse edge parsing and coloring from tdd-debug-diagram.py
FAILURE_KEYWORDS = re.compile(
    r"fail|error|stuck|reject|crash|timeout|broken|"
    r"changes needed|issues|no\b|can.t|cannot|inconclusive|"
    r"3\+\s*failures",
    re.IGNORECASE,
)

COLOR_SUCCESS = "#4CAF50"
COLOR_FAILURE = "#F44336"
COLOR_UNUSED = "#9E9E9E"


def find_edges(lines):
    """Find all edge lines (reused from tdd-debug-diagram.py)."""
    edges = []
    edge_pattern = re.compile(
        r"(\b[A-Z][A-Z0-9_]*\b)\s*(--[->.]*)(\|([^|]*)\|)?\s*(\b[A-Z][A-Z0-9_]*\b)"
    )
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("classDef", "style", "%%")):
            continue
        m = edge_pattern.search(line)
        if m:
            label = m.group(4) or ""
            label_clean = label.strip().strip('"')
            is_failure = bool(FAILURE_KEYWORDS.search(label_clean))
            edges.append({
                "index": len(edges),
                "line": i,
                "src": m.group(1),
                "dst": m.group(5),
                "label": label_clean,
                "is_failure": is_failure,
            })
    return edges


def annotate_mermaid(mermaid_template, edge_counts, used_nodes=None):
    """Annotate a mermaid diagram with colors and traversal counts.

    Args:
        mermaid_template: Raw mermaid flowchart string
        edge_counts: Dict of "SRC->DST": count
        used_nodes: Set of node IDs that were used (colored green)

    Returns:
        Annotated mermaid string
    """
    lines = mermaid_template.splitlines()
    edges = find_edges(lines)
    used_nodes = used_nodes or set()

    # Parse edge_counts into set of traversed edges
    traversed = set()
    for edge_key, count in edge_counts.items():
        if count > 0 and "->" in edge_key:
            parts = edge_key.split("->")
            if len(parts) == 2:
                traversed.add((parts[0].strip(), parts[1].strip()))

    # Add traversal counts to edge labels
    for edge_key, count in edge_counts.items():
        if count <= 0:
            continue
        parts = edge_key.split("->")
        if len(parts) != 2:
            continue
        src, dst = parts[0].strip(), parts[1].strip()
        for i, line in enumerate(lines):
            pattern = rf"(\b{re.escape(src)}\b\s*)(--[->.]*)(\|[^|]*\|)?(\s*{re.escape(dst)}\b)"
            m = re.search(pattern, line)
            if m:
                count_str = f"{count}x"
                old_label = m.group(3)
                if old_label:
                    inner = old_label.strip("|").strip().strip('"')
                    new_label = f'|"{inner} ({count_str})"|'
                else:
                    new_label = f'|"{count_str}"|'
                new_line = (
                    line[: m.start()] + m.group(1) + m.group(2) + new_label + line[m.start(4):]
                )
                lines[i] = new_line
                break

    # Add linkStyle directives for edge coloring
    link_styles = []
    for edge in edges:
        key = (edge["src"], edge["dst"])
        if key in traversed:
            color = COLOR_FAILURE if edge["is_failure"] else COLOR_SUCCESS
        else:
            color = COLOR_UNUSED
        link_styles.append(f"    linkStyle {edge['index']} stroke:{color},stroke-width:2px")

    # Add node styles for used nodes
    node_styles = []
    for node_id in used_nodes:
        node_styles.append(f"    style {node_id} fill:#C8E6C9,stroke:#4CAF50,stroke-width:3px")

    # Insert before classDef lines
    insert_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith(("classDef", "style ")):
            insert_idx = i
            break

    for j, style in enumerate(link_styles + node_styles):
        lines.insert(insert_idx + j, style)

    return "\n".join(lines)


def run_mermaid(args):
    """Run the mermaid phase: generate annotated diagrams from stats."""
    stats_file = args.stats_file
    if not stats_file:
        print("ERROR: --stats-file is required for mermaid phase", file=sys.stderr)
        sys.exit(1)

    with open(stats_file) as f:
        stats = json.load(f)

    skills_dir = args.skills_dir or os.path.join(os.getcwd(), ".claude", "skills")
    diagrams = {}

    # For each workflow that has edge data, generate annotated diagram
    for workflow_name, edge_counts in stats.get("workflow_edges", {}).items():
        template = find_skill_workflow(workflow_name, skills_dir)
        if template:
            # Determine which nodes were used
            used_nodes = set()
            for edge_key in edge_counts:
                if edge_counts[edge_key] > 0 and "->" in edge_key:
                    parts = edge_key.split("->")
                    used_nodes.add(parts[0].strip())
                    used_nodes.add(parts[1].strip())

            annotated = annotate_mermaid(template, edge_counts, used_nodes)
            diagrams[workflow_name] = annotated

    # Also check skills_invoked for workflows
    for skill_info in stats.get("skills_invoked", []):
        skill_name = skill_info["skill"]
        if skill_name not in diagrams:
            template = find_skill_workflow(skill_name, skills_dir)
            if template:
                diagrams[skill_name] = template  # No edge data, show grey

    # Save diagrams
    output_dir = os.path.dirname(stats_file)
    diagrams_file = os.path.join(output_dir, "diagrams.json")
    with open(diagrams_file, "w") as f:
        json.dump(diagrams, f, indent=2)
    print(f"Diagrams: {diagrams_file}")
    print(f"Generated {len(diagrams)} workflow diagrams: {', '.join(diagrams.keys())}")
```

**Step 2: Test with real stats**

Run: `python3 .claude/scripts/session-analytics.py --phase mermaid --stats-file /tmp/kagenti/session/00b11888-stats.json --skills-dir .claude/skills/`
Expected: Diagrams JSON written with annotated Mermaid content.

**Step 3: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement --phase mermaid for workflow diagram annotation"
```

---

### Task 4: Implement --phase comment (GitHub comment posting)

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

**Step 1: Implement comment formatting and posting**

```python
import subprocess


SESSION_MARKER_PREFIX = "<!-- SESSION:"
SUMMARY_MARKER = "<!-- SESSION_SUMMARY -->"


def format_duration(minutes):
    """Format minutes as Xh Ym."""
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def format_tokens(n):
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K" if n >= 10_000 else f"{n:,}"
    return str(n)


def format_session_comment(stats, diagrams=None):
    """Format session stats as a GitHub comment markdown string."""
    sid = stats["session_id_short"]
    models_list = ", ".join(stats["models"].keys())
    duration = format_duration(stats["duration_minutes"])
    cost = f"${stats['estimated_cost_usd']}"
    commits_count = len(stats.get("commits", []))
    skills_list = ", ".join(s["skill"] for s in stats.get("skills_invoked", []))

    lines = []
    lines.append(f"{SESSION_MARKER_PREFIX}{stats['session_id'][:16]} -->")
    lines.append("")
    lines.append("## Claude Code Session Report")
    lines.append("")

    # TL;DR
    tldr_parts = [f"Session `{sid}`", models_list, duration, cost, f"{commits_count} commits"]
    if skills_list:
        tldr_parts.append(skills_list)
    lines.append(f"**TL;DR:** {' | '.join(tldr_parts)}")
    lines.append("")

    # Header
    branch = stats.get("branch", "unknown")
    lines.append(f"**Session:** `{sid}` | **Branch:** `{branch}` | **Duration:** {duration}")
    lines.append("")

    # Token usage table
    lines.append("### Token Usage")
    lines.append("")
    lines.append("| Model | Input | Output | Cache Create | Cache Read | Est. Cost |")
    lines.append("|-------|-------|--------|-------------|------------|-----------|")
    for model, m in stats["models"].items():
        model_cost = estimate_cost(model, {
            "input_tokens": m["input_tokens"],
            "output_tokens": m["output_tokens"],
            "cache_creation_input_tokens": m["cache_creation_tokens"],
            "cache_read_input_tokens": m["cache_read_tokens"],
        })
        lines.append(
            f"| {model} | {format_tokens(m['input_tokens'])} | {format_tokens(m['output_tokens'])} | "
            f"{format_tokens(m['cache_creation_tokens'])} | {format_tokens(m['cache_read_tokens'])} | ${model_cost:.2f} |"
        )
    t = stats["total_tokens"]
    lines.append(
        f"| **Total** | **{format_tokens(t['input'])}** | **{format_tokens(t['output'])}** | "
        f"**{format_tokens(t['cache_creation'])}** | **{format_tokens(t['cache_read'])}** | **{cost}** |"
    )
    lines.append("")

    # Subagents
    subs = stats.get("subagents", [])
    if subs:
        lines.append("### Subagents")
        lines.append("")
        lines.append("| ID | Type | Model | Input | Output |")
        lines.append("|----|------|-------|-------|--------|")
        for s in subs:
            lines.append(
                f"| {s['id'][:7]} | {s['type']} | {s['model']} | "
                f"{format_tokens(s['tokens']['input'])} | {format_tokens(s['tokens']['output'])} |"
            )
        lines.append("")

    # Skills
    skills = stats.get("skills_invoked", [])
    if skills:
        lines.append("### Skills")
        lines.append("")
        lines.append("| Skill | Invocations | Status |")
        lines.append("|-------|-------------|--------|")
        for s in skills:
            status = "pass" if s["status"] == "pass" else s["status"]
            lines.append(f"| {s['skill']} | {s['count']} | {status} |")
        lines.append("")

    # Tools (collapsible)
    tools = stats.get("tools", {})
    if tools:
        lines.append("<details><summary>Tool Usage</summary>")
        lines.append("")
        lines.append("| Tool | Count |")
        lines.append("|------|-------|")
        for tool, count in sorted(tools.items(), key=lambda x: -x[1]):
            lines.append(f"| {tool} | {count} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Workflow diagrams
    if diagrams:
        for workflow_name, mermaid_content in diagrams.items():
            lines.append(f"### {workflow_name.replace(':', ' ').title()} Workflow")
            lines.append("")
            lines.append("```mermaid")
            lines.append(mermaid_content)
            lines.append("```")
            lines.append("")

    # Problems
    problems = stats.get("problems_faced", [])
    if problems:
        lines.append("### Problems Faced")
        lines.append("")
        lines.append("| Problem | Resolved | Iterations |")
        lines.append("|---------|----------|------------|")
        for p in problems:
            resolved = "yes" if p.get("resolved") else "no"
            lines.append(f"| {p['description']} | {resolved} | {p.get('iterations', '-')} |")
        lines.append("")

    # Commits
    commits = stats.get("commits", [])
    if commits:
        lines.append("### Commits")
        lines.append("")
        for c in commits:
            sha = c.get("sha", "")[:7] if c.get("sha") else "-"
            lines.append(f"- `{sha}` {c.get('message', '')}")
        lines.append("")

    # Session data (collapsible JSON for machine parsing)
    lines.append("<details><summary>Session Data (JSON)</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(stats, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("</details>")

    return "\n".join(lines)


def gh_find_comment(repo, target, number, marker):
    """Find an existing comment with a specific marker."""
    endpoint = f"repos/{repo}/issues/{number}/comments"
    result = subprocess.run(
        ["gh", "api", endpoint, "--paginate", "--jq",
         f'.[] | select(.body | contains("{marker}")) | .id'],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split("\n")[0]
    return None


def gh_post_comment(repo, number, body):
    """Post a new comment on a PR/issue."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{number}/comments",
         "-f", f"body={body}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"ERROR posting comment: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(result.stdout)
    return data.get("id")


def gh_update_comment(repo, comment_id, body):
    """Update an existing comment."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/comments/{comment_id}",
         "-X", "PATCH", "-f", f"body={body}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"ERROR updating comment: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def run_comment(args):
    """Run the comment phase: post/update session comment on PR/issue."""
    if not all([args.stats_file, args.target, args.number, args.repo]):
        print("ERROR: --stats-file, --target, --number, --repo required", file=sys.stderr)
        sys.exit(1)

    with open(args.stats_file) as f:
        stats = json.load(f)

    # Load diagrams if available
    diagrams_file = os.path.join(os.path.dirname(args.stats_file), "diagrams.json")
    diagrams = {}
    if os.path.exists(diagrams_file):
        with open(diagrams_file) as f:
            diagrams = json.load(f)

    body = format_session_comment(stats, diagrams)

    # Find existing comment for this session
    marker = f"{SESSION_MARKER_PREFIX}{stats['session_id'][:16]}"
    existing_id = gh_find_comment(args.repo, args.target, args.number, marker)

    if existing_id:
        gh_update_comment(args.repo, existing_id, body)
        print(f"Updated comment {existing_id} on {args.target} #{args.number}")
    else:
        new_id = gh_post_comment(args.repo, args.number, body)
        print(f"Posted new comment {new_id} on {args.target} #{args.number}")
```

**Step 2: Test comment formatting locally**

Run: `python3 -c "
import json, sys; sys.path.insert(0, '.claude/scripts')
exec(open('.claude/scripts/session-analytics.py').read())
with open('/tmp/kagenti/session/00b11888-stats.json') as f:
    stats = json.load(f)
print(format_session_comment(stats))
"`
Expected: Well-formatted markdown output.

**Step 3: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement --phase comment for GitHub comment posting"
```

---

### Task 5: Implement --phase summary (pinned summary comment)

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

**Step 1: Implement summary phase**

The summary always recalculates from individual session comments to ensure sums match exactly.

```python
def parse_session_data_from_comment(comment_body):
    """Extract the JSON stats from a session comment's collapsible block."""
    match = re.search(r"```json\n(.*?)```", comment_body, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def format_summary_comment(sessions):
    """Format a pinned summary comment from individual session data."""
    if not sessions:
        return ""

    total_cost = sum(s.get("estimated_cost_usd", 0) for s in sessions)
    total_commits = sum(len(s.get("commits", [])) for s in sessions)

    # Aggregate models
    model_totals = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
    })
    for s in sessions:
        for model, m in s.get("models", {}).items():
            mt = model_totals[model]
            mt["input_tokens"] += m.get("input_tokens", 0)
            mt["output_tokens"] += m.get("output_tokens", 0)
            mt["cache_creation_tokens"] += m.get("cache_creation_tokens", 0)
            mt["cache_read_tokens"] += m.get("cache_read_tokens", 0)

    lines = []
    lines.append(SUMMARY_MARKER)
    lines.append("")
    lines.append("## Claude Code PR Summary")
    lines.append("")

    # TL;DR
    lines.append(f"**TL;DR:** {len(sessions)} sessions | ${total_cost:.2f} total | {total_commits} commits")
    lines.append("")
    lines.append(f"**Sessions:** {len(sessions)} | **Total Cost:** ${total_cost:.2f} | **Commits:** {total_commits}")
    lines.append("")

    # Aggregate token usage
    lines.append("### Aggregate Token Usage")
    lines.append("")
    lines.append("| Model | Input | Output | Cache Create | Cache Read | Est. Cost |")
    lines.append("|-------|-------|--------|-------------|------------|-----------|")
    for model, mt in model_totals.items():
        model_cost = estimate_cost(model, {
            "input_tokens": mt["input_tokens"],
            "output_tokens": mt["output_tokens"],
            "cache_creation_input_tokens": mt["cache_creation_tokens"],
            "cache_read_input_tokens": mt["cache_read_tokens"],
        })
        lines.append(
            f"| {model} | {format_tokens(mt['input_tokens'])} | {format_tokens(mt['output_tokens'])} | "
            f"{format_tokens(mt['cache_creation_tokens'])} | {format_tokens(mt['cache_read_tokens'])} | ${model_cost:.2f} |"
        )
    lines.append("")

    # Session history table
    lines.append("### Session History")
    lines.append("")
    lines.append("| # | Session | Duration | Cost | Skills | Commits | Status |")
    lines.append("|---|---------|----------|------|--------|---------|--------|")
    for i, s in enumerate(sessions, 1):
        sid = s.get("session_id_short", "?")
        duration = format_duration(s.get("duration_minutes", 0))
        cost = f"${s.get('estimated_cost_usd', 0):.2f}"
        skills = ", ".join(sk["skill"] for sk in s.get("skills_invoked", []))
        commits = len(s.get("commits", []))
        lines.append(f"| {i} | `{sid}` | {duration} | {cost} | {skills or '-'} | {commits} | done |")
    lines.append("")

    # Totals verification
    lines.append("### Totals Verification")
    lines.append("")
    cost_parts = " + ".join(f"${s.get('estimated_cost_usd', 0):.2f}" for s in sessions)
    lines.append(f"- Sum of session costs: {cost_parts} = **${total_cost:.2f}**")
    commit_parts = " + ".join(str(len(s.get("commits", []))) for s in sessions)
    lines.append(f"- Sum of session commits: {commit_parts} = **{total_commits}**")
    lines.append("")

    # Summary data (collapsible JSON)
    summary_data = {
        "total_sessions": len(sessions),
        "total_cost_usd": round(total_cost, 2),
        "total_commits": total_commits,
        "sessions": [s.get("session_id_short", "?") for s in sessions],
    }
    lines.append("<details><summary>Summary Data (JSON)</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(summary_data, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("</details>")

    return "\n".join(lines)


def run_summary(args):
    """Run the summary phase: recalculate and post/update pinned summary."""
    if not all([args.number, args.repo]):
        print("ERROR: --number and --repo required for summary phase", file=sys.stderr)
        sys.exit(1)

    # Fetch all comments on the PR/issue
    endpoint = f"repos/{args.repo}/issues/{args.number}/comments"
    result = subprocess.run(
        ["gh", "api", endpoint, "--paginate", "--jq", ".[].body"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"ERROR fetching comments: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse session data from each session comment
    sessions = []
    # Split by the JSONL-like output (each body is on its own line in --jq output)
    # Actually gh api --jq ".[].body" outputs each body, but they may contain newlines
    # Better approach: use JSON output and parse
    result = subprocess.run(
        ["gh", "api", endpoint, "--paginate"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"ERROR fetching comments: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    comments = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(comments, dict):
        comments = [comments]

    for comment in comments:
        body = comment.get("body", "")
        if SESSION_MARKER_PREFIX in body and SUMMARY_MARKER not in body:
            session_data = parse_session_data_from_comment(body)
            if session_data:
                sessions.append(session_data)

    if not sessions:
        print("No session comments found, nothing to summarize.")
        return

    # Generate summary
    body = format_summary_comment(sessions)

    # Find existing summary comment
    existing_id = gh_find_comment(args.repo, "pr", args.number, SUMMARY_MARKER)

    if existing_id:
        gh_update_comment(args.repo, existing_id, body)
        print(f"Updated summary comment {existing_id}")
    else:
        new_id = gh_post_comment(args.repo, args.number, body)
        print(f"Posted new summary comment {new_id}")

    print(f"Summary: {len(sessions)} sessions, ${sum(s.get('estimated_cost_usd', 0) for s in sessions):.2f} total")
```

**Step 2: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement --phase summary for pinned summary comment"
```

---

### Task 6: Implement --phase extract (CSV/MD/HTML extraction)

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

**Step 1: Implement extract phase**

```python
import csv


def run_extract(args):
    """Extract session data from PR/issue comments to CSV/MD/HTML."""
    if not args.repo:
        print("ERROR: --repo required for extract phase", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Fetch PRs and issues in date range
    date_filter = ""
    if args.from_date:
        date_filter += f" created:>={args.from_date}"
    if args.to_date:
        date_filter += f" created:<={args.to_date}"

    all_rows = []

    for target_type in ["pr", "issue"]:
        # Fetch list
        if target_type == "pr":
            cmd = [
                "gh", "pr", "list", "--repo", args.repo, "--state", "all",
                "--limit", "500",
                "--json", "number,title,author,state,additions,deletions,mergedAt,createdAt,closedAt,reviewDecision",
            ]
            if args.from_date:
                cmd.extend(["--search", f"created:>={args.from_date}"])
        else:
            cmd = [
                "gh", "issue", "list", "--repo", args.repo, "--state", "all",
                "--limit", "500",
                "--json", "number,title,author,state,createdAt,closedAt",
            ]
            if args.from_date:
                cmd.extend(["--search", f"created:>={args.from_date}"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"WARNING: failed to list {target_type}s: {result.stderr}", file=sys.stderr)
            continue

        items = json.loads(result.stdout) if result.stdout.strip() else []

        for item in items:
            number = item["number"]

            # Fetch comments
            endpoint = f"repos/{args.repo}/issues/{number}/comments"
            result = subprocess.run(
                ["gh", "api", endpoint, "--paginate"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                continue

            comments = json.loads(result.stdout) if result.stdout.strip() else []
            if isinstance(comments, dict):
                comments = [comments]

            for comment in comments:
                body = comment.get("body", "")
                if SESSION_MARKER_PREFIX not in body or SUMMARY_MARKER in body:
                    continue

                session_data = parse_session_data_from_comment(body)
                if not session_data:
                    continue

                # Build CSV row
                row = {
                    "pr_number": number,
                    "target_type": target_type,
                    "pr_title": item.get("title", ""),
                    "pr_author": item.get("author", {}).get("login", "") if isinstance(item.get("author"), dict) else str(item.get("author", "")),
                    "pr_status": item.get("state", ""),
                    "session_id": session_data.get("session_id", ""),
                    "session_started": session_data.get("started_at", ""),
                    "session_duration_min": session_data.get("duration_minutes", 0),
                    "models_used": ",".join(session_data.get("models", {}).keys()),
                    "total_input_tokens": session_data.get("total_tokens", {}).get("input", 0),
                    "total_output_tokens": session_data.get("total_tokens", {}).get("output", 0),
                    "total_cache_create": session_data.get("total_tokens", {}).get("cache_creation", 0),
                    "total_cache_read": session_data.get("total_tokens", {}).get("cache_read", 0),
                    "estimated_cost_usd": session_data.get("estimated_cost_usd", 0),
                    "commits_count": len(session_data.get("commits", [])),
                    "commit_shas": ";".join(c.get("sha", "") for c in session_data.get("commits", []) if c.get("sha")),
                    "skills_used": ",".join(s["skill"] for s in session_data.get("skills_invoked", [])),
                    "per_skill_tokens": json.dumps({s["skill"]: s.get("tokens", {}) for s in session_data.get("skills_invoked", []) if s.get("tokens")}),
                    "subagent_count": len(session_data.get("subagents", [])),
                    "per_subagent_tokens": json.dumps({s["type"]: s.get("tokens", {}) for s in session_data.get("subagents", []) if s.get("tokens")}),
                    "problems_count": len(session_data.get("problems_faced", [])),
                    "problems_resolved": sum(1 for p in session_data.get("problems_faced", []) if p.get("resolved")),
                    "lines_added": item.get("additions", 0),
                    "lines_removed": item.get("deletions", 0),
                    "time_to_merge_hours": "",
                    "acceptance_status": "merged" if item.get("mergedAt") else item.get("state", ""),
                }

                # Calculate time to merge
                if item.get("mergedAt") and item.get("createdAt"):
                    try:
                        created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
                        merged = datetime.fromisoformat(item["mergedAt"].replace("Z", "+00:00"))
                        row["time_to_merge_hours"] = round((merged - created).total_seconds() / 3600, 1)
                    except (ValueError, TypeError):
                        pass

                all_rows.append(row)

    if not all_rows:
        print("No session data found in comments.")
        return

    # Write CSV
    csv_path = os.path.join(args.output_dir, "analytics.csv")
    fieldnames = list(all_rows[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"CSV: {csv_path} ({len(all_rows)} rows)")

    # Write MD report
    md_path = os.path.join(args.output_dir, "analytics.md")
    write_md_report(all_rows, md_path, args)
    print(f"MD: {md_path}")

    # Write HTML dashboard
    html_path = os.path.join(args.output_dir, "dashboard.html")
    write_html_dashboard(all_rows, html_path, args)
    print(f"HTML: {html_path}")


def write_md_report(rows, path, args):
    """Write a markdown analytics report."""
    total_cost = sum(r["estimated_cost_usd"] for r in rows)
    total_sessions = len(rows)
    unique_prs = len(set(r["pr_number"] for r in rows if r["target_type"] == "pr"))
    unique_issues = len(set(r["pr_number"] for r in rows if r["target_type"] == "issue"))
    merged_count = sum(1 for r in rows if r["acceptance_status"] == "merged")

    lines = [
        "# Claude Code Analytics Report",
        "",
        f"**Period:** {args.from_date or 'all'} to {args.to_date or 'now'}",
        f"**Repository:** {args.repo}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| PRs with session data | {unique_prs} |",
        f"| Issues with session data | {unique_issues} |",
        f"| Total sessions | {total_sessions} |",
        f"| Total cost | ${total_cost:.2f} |",
        f"| Average cost per session | ${total_cost / total_sessions:.2f} |" if total_sessions else "| Average cost per session | - |",
        f"| PR acceptance rate | {merged_count / unique_prs * 100:.0f}% |" if unique_prs else "| PR acceptance rate | - |",
        "",
        "## Per-PR Breakdown",
        "",
        "| PR# | Title | Sessions | Cost | Commits | Status |",
        "|-----|-------|----------|------|---------|--------|",
    ]

    # Group by PR
    from itertools import groupby
    pr_rows = sorted([r for r in rows if r["target_type"] == "pr"], key=lambda r: r["pr_number"])
    for pr_num, group in groupby(pr_rows, key=lambda r: r["pr_number"]):
        sessions = list(group)
        pr_cost = sum(s["estimated_cost_usd"] for s in sessions)
        pr_commits = sum(s["commits_count"] for s in sessions)
        lines.append(
            f"| #{pr_num} | {sessions[0]['pr_title'][:50]} | {len(sessions)} | ${pr_cost:.2f} | {pr_commits} | {sessions[0]['acceptance_status']} |"
        )

    lines.extend([
        "",
        "## Model Usage Distribution",
        "",
        "| Model | Sessions |",
        "|-------|----------|",
    ])
    model_counts = Counter()
    for r in rows:
        for m in r["models_used"].split(","):
            if m:
                model_counts[m] += 1
    for model, count in model_counts.most_common():
        lines.append(f"| {model} | {count} |")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
```

**Step 2: Implement HTML dashboard**

```python
def write_html_dashboard(rows, path, args):
    """Write an HTML dashboard with Chart.js charts."""
    total_cost = sum(r["estimated_cost_usd"] for r in rows)

    # Prepare chart data
    pr_costs = {}
    for r in rows:
        key = f"#{r['pr_number']}"
        pr_costs[key] = pr_costs.get(key, 0) + r["estimated_cost_usd"]

    # Skill frequency
    skill_freq = Counter()
    for r in rows:
        for s in r["skills_used"].split(","):
            if s:
                skill_freq[s] += 1

    # Model distribution
    model_dist = Counter()
    for r in rows:
        for m in r["models_used"].split(","):
            if m:
                model_dist[m] += 1

    html = f"""<!DOCTYPE html>
<html><head>
<title>Claude Code Analytics - {args.repo}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
  h1, h2 {{ color: #333; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .stat {{ font-size: 2em; font-weight: bold; color: #2196F3; }}
  .stat-label {{ color: #666; font-size: 0.9em; }}
  canvas {{ max-height: 300px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
</style>
</head><body>
<h1>Claude Code Analytics</h1>
<p>{args.repo} | {args.from_date or 'all'} to {args.to_date or 'now'}</p>

<div class="grid">
  <div class="card"><div class="stat">{len(rows)}</div><div class="stat-label">Sessions</div></div>
  <div class="card"><div class="stat">${total_cost:.2f}</div><div class="stat-label">Total Cost</div></div>
  <div class="card"><div class="stat">{len(set(r['pr_number'] for r in rows))}</div><div class="stat-label">PRs/Issues</div></div>
  <div class="card"><div class="stat">{sum(r['commits_count'] for r in rows)}</div><div class="stat-label">Commits</div></div>
</div>

<div class="grid" style="margin-top: 20px;">
  <div class="card">
    <h2>Cost per PR</h2>
    <canvas id="costChart"></canvas>
  </div>
  <div class="card">
    <h2>Skills Usage</h2>
    <canvas id="skillsChart"></canvas>
  </div>
  <div class="card">
    <h2>Model Distribution</h2>
    <canvas id="modelChart"></canvas>
  </div>
  <div class="card">
    <h2>Sessions Over Time</h2>
    <canvas id="timeChart"></canvas>
  </div>
</div>

<script>
new Chart(document.getElementById('costChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(pr_costs.keys()))},
    datasets: [{{ label: 'Cost ($)', data: {json.dumps(list(pr_costs.values()))}, backgroundColor: '#2196F3' }}]
  }}
}});

new Chart(document.getElementById('skillsChart'), {{
  type: 'pie',
  data: {{
    labels: {json.dumps(list(skill_freq.keys()))},
    datasets: [{{ data: {json.dumps(list(skill_freq.values()))}, backgroundColor: ['#4CAF50','#FF9800','#2196F3','#9C27B0','#F44336','#00BCD4'] }}]
  }}
}});

new Chart(document.getElementById('modelChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(list(model_dist.keys()))},
    datasets: [{{ data: {json.dumps(list(model_dist.values()))}, backgroundColor: ['#3F51B5','#FF5722','#4CAF50'] }}]
  }}
}});

// Time chart - sessions per day
const dates = {json.dumps(sorted(set(r['session_started'][:10] for r in rows if r['session_started'])))};
const dateCounts = dates.map(d => {json.dumps({r['session_started'][:10]: 1 for r in rows if r['session_started']})}.hasOwnProperty(d) ? 1 : 0);
new Chart(document.getElementById('timeChart'), {{
  type: 'line',
  data: {{
    labels: dates,
    datasets: [{{ label: 'Sessions', data: dateCounts, borderColor: '#4CAF50', fill: false }}]
  }}
}});
</script>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)
```

**Step 3: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement --phase extract with CSV/MD/HTML output"
```

---

### Task 7: Implement full pipeline and self-test

**Files:**
- Modify: `.claude/scripts/session-analytics.py`

**Step 1: Implement full pipeline**

```python
def run_full_pipeline(args):
    """Run all phases in sequence: stats -> mermaid -> comment -> summary."""
    if not args.session_id:
        print("ERROR: --session-id required for full pipeline", file=sys.stderr)
        sys.exit(1)
    if not all([args.target, args.number, args.repo]):
        print("ERROR: --target, --number, --repo required for full pipeline", file=sys.stderr)
        sys.exit(1)

    print("=== Phase 1: Stats ===")
    run_stats(args)

    # Set stats file for subsequent phases if not set
    if not args.stats_file:
        args.stats_file = f"/tmp/kagenti/session/{args.session_id[:8]}-stats.json"

    print("\n=== Phase 2: Mermaid ===")
    run_mermaid(args)

    print("\n=== Phase 3: Comment ===")
    run_comment(args)

    print("\n=== Phase 4: Summary ===")
    run_summary(args)

    print("\n=== Pipeline complete ===")
```

**Step 2: Add self-test mode**

Add `--self-test` flag that:
1. Creates a minimal JSONL fixture in `/tmp/kagenti/session/test/`
2. Runs `--phase stats` against it
3. Runs `--phase mermaid` against the output
4. Verifies the comment format
5. Does NOT post to GitHub

**Step 3: Test full pipeline locally (without posting)**

Run: `python3 .claude/scripts/session-analytics.py --self-test`
Expected: All phases pass, formatted markdown output displayed.

**Step 4: Commit**

```bash
git add .claude/scripts/session-analytics.py
git commit -s -m "feat: implement full pipeline and self-test mode"
```

---

### Task 8: Create session/ skill files

**Files:**
- Create: `.claude/skills/session/SKILL.md`
- Create: `.claude/skills/session:post/SKILL.md`
- Create: `.claude/skills/session:summary/SKILL.md`
- Create: `.claude/skills/session:extract/SKILL.md`
- Create: `.claude/skills/session:dashboard/SKILL.md`

**Step 1: Create router skill**

Create `.claude/skills/session/SKILL.md`:

```markdown
---
name: session
description: Claude Code session analytics - post stats to PRs/issues, extract to CSV
---

# Session Analytics

Track and report Claude Code session metadata on GitHub PRs and issues.

## Router

When `/session` is invoked, determine what to do:

- Post session stats to PR/issue -> `session:post`
- Update pinned summary comment -> `session:summary`
- Extract analytics to CSV/MD/HTML -> `session:extract`
- Generate dashboard -> `session:dashboard`

## Quick Reference

| Task | Skill | Command |
|------|-------|---------|
| Post current session | `session:post` | After TDD/RCA completion |
| Update summary | `session:summary` | Auto-called by session:post |
| Extract data | `session:extract` | For analytics/reporting |
| Dashboard | `session:dashboard` | Interactive HTML charts |
```

**Step 2: Create sub-skills**

Create each sub-skill SKILL.md with instructions for invoking `session-analytics.py` with the right `--phase` and arguments. Each skill should:

1. Detect the current session ID from the environment
2. Detect the current PR/issue from git branch + `gh pr list`
3. Invoke the script with the right parameters
4. Report results

**Step 3: Commit**

```bash
git add .claude/skills/session/ .claude/skills/session:post/ .claude/skills/session:summary/ .claude/skills/session:extract/ .claude/skills/session:dashboard/
git commit -s -m "feat: create session/ skill files for analytics"
```

---

### Task 9: Update settings.json for new skills

**Files:**
- Modify: `.claude/settings.json`

**Step 1: Add auto-approve rules for session analytics**

Add to the allowedTools list:
- `Bash(python3 .claude/scripts/session-analytics.py *)` - allow running the analytics script
- `Bash(gh api repos/*/issues/*/comments *)` - allow reading/posting comments

**Step 2: Commit**

```bash
git add .claude/settings.json
git commit -s -m "chore: add session analytics to auto-approve rules"
```

---

### Task 10: Update skills README with session category

**Files:**
- Modify: `.claude/skills/README.md`

**Step 1: Add session/ to the skill tree**

Add the session category to the Complete Skill Tree section and add a Session Analytics workflow diagram in Mermaid.

**Step 2: Commit**

```bash
git add .claude/skills/README.md
git commit -s -m "docs: add session analytics to skills README"
```

---

### Task 11: Integration hooks in TDD/RCA skills

**Files:**
- Modify: `.claude/skills/tdd:ci/SKILL.md` (add session:post note at Phase 8)
- Modify: `.claude/skills/tdd:hypershift/SKILL.md` (add session:post note)
- Modify: `.claude/skills/tdd:kind/SKILL.md` (add session:post note)

**Step 1: Add session reporting to TDD completion**

At the end of each TDD skill's final phase (after CI green/merged), add a section:

```markdown
## Session Reporting

After the TDD workflow completes (CI green and PR approved/merged), invoke `session:post` to capture session metadata:

1. The skill auto-detects the current session ID and PR number
2. Posts a session report comment with token usage, skills used, and workflow diagram
3. Updates the pinned summary comment

This is optional but recommended for tracking development effort.
```

**Step 2: Commit**

```bash
git add .claude/skills/tdd:ci/SKILL.md .claude/skills/tdd:hypershift/SKILL.md .claude/skills/tdd:kind/SKILL.md
git commit -s -m "feat: add session:post integration hooks to TDD skills"
```

---

### Task 12: End-to-end test on a real PR

**Step 1: Run the full pipeline on a test PR**

1. Pick an existing PR (or the current PR for this branch)
2. Run: `python3 .claude/scripts/session-analytics.py --phase stats --session-id <current-session>`
3. Run: `python3 .claude/scripts/session-analytics.py --phase mermaid --stats-file /tmp/kagenti/session/<id>-stats.json`
4. Review the formatted comment output locally
5. Post to the PR: `python3 .claude/scripts/session-analytics.py --phase comment --stats-file /tmp/kagenti/session/<id>-stats.json --target pr --number <N> --repo kagenti/kagenti`
6. Verify the comment appears correctly on GitHub
7. Run summary: `python3 .claude/scripts/session-analytics.py --phase summary --number <N> --repo kagenti/kagenti`
8. Verify the pinned summary matches the individual comment

**Step 2: Run extract on the same PR**

1. Run: `python3 .claude/scripts/session-analytics.py --phase extract --repo kagenti/kagenti --from-date 2026-02-15 --output-dir /tmp/kagenti/session/`
2. Verify CSV has correct columns and data
3. Verify MD report is readable
4. Open HTML dashboard in browser

**Step 3: Fix any issues found during testing**

**Step 4: Final commit**

```bash
git add -A
git commit -s -m "fix: address issues found during E2E testing"
```
