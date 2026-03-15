#!/usr/bin/env python3
"""Analyze Claude Code JSONL session files and produce structured analytics.

Pipeline phases:
  stats     - Parse JSONL, extract token usage, tools, costs -> JSON
  mermaid   - Generate annotated workflow diagrams from stats + SKILL.md templates
  comment   - Post PR/issue comment with session summary (placeholder)
  summary   - Generate human-readable summary (placeholder)
  extract   - Export sessions from PR/issue comments to CSV/MD/HTML
  dashboard - Aggregate multi-session dashboard (placeholder)

Usage:
    python3 .claude/scripts/session-analytics.py \\
        --phase stats --session-id <UUID>

    python3 .claude/scripts/session-analytics.py \\
        --phase stats --session-id <UUID> --stats-file /tmp/out.json

    python3 .claude/scripts/session-analytics.py --self-test
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

OUTPUT_BASE = Path("/tmp/kagenti/session")

# Pricing per 1M tokens (USD)
MODEL_PRICING = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_create": 18.75,
        "cache_read": 1.50,
    },
    "claude-opus-4-5-20251101": {
        "input": 15.0,
        "output": 75.0,
        "cache_create": 18.75,
        "cache_read": 1.50,
    },
    "claude-sonnet-4-5-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_create": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_create": 1.0,
        "cache_read": 0.08,
    },
}

# Fallback pricing for unknown models (use opus pricing as conservative default)
FALLBACK_PRICING = {
    "input": 15.0,
    "output": 75.0,
    "cache_create": 18.75,
    "cache_read": 1.50,
}

# GitHub comment markers
SESSION_MARKER_PREFIX = "<!-- SESSION:"
SUMMARY_MARKER = "<!-- SESSION_SUMMARY -->"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Analyze Claude Code JSONL session files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--phase",
        choices=["stats", "mermaid", "comment", "summary", "extract", "dashboard"],
        required=False,
        help="Pipeline phase to execute",
    )
    p.add_argument("--session-id", help="Session UUID to analyze")
    p.add_argument(
        "--project-dir",
        help="Claude Code project dir (default: auto-detect from ~/.claude/projects/)",
    )
    p.add_argument(
        "--stats-file",
        help="Path to stats JSON (input for downstream phases, output for stats phase)",
    )
    p.add_argument("--skills-dir", help="Path to .claude/skills/ directory")
    p.add_argument(
        "--target",
        choices=["pr", "issue"],
        help="GitHub target type for comment phase",
    )
    p.add_argument("--number", type=int, help="PR or issue number")
    p.add_argument("--repo", help="GitHub repo (OWNER/NAME)")
    p.add_argument("--from-date", help="Start date for extract (YYYY-MM-DD)")
    p.add_argument("--to-date", help="End date for extract (YYYY-MM-DD)")
    p.add_argument(
        "--output-dir",
        default=str(OUTPUT_BASE),
        help=f"Output directory (default: {OUTPUT_BASE})",
    )
    p.add_argument(
        "--diagrams-file",
        help="Path to diagrams JSON file (for comment phase)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print comment body without posting to GitHub",
    )
    p.add_argument(
        "--self-test", action="store_true", help="Run built-in self-test mode"
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# JSONL discovery
# ---------------------------------------------------------------------------


def find_session_jsonl(session_id, project_dir=None):
    """Locate the JSONL file for a given session UUID.

    Search order:
    1. If project_dir is given, look there directly.
    2. Scan all directories under ~/.claude/projects/ for <session_id>.jsonl
    """
    filename = f"{session_id}.jsonl"

    if project_dir:
        candidate = Path(project_dir) / filename
        if candidate.is_file():
            return candidate
        # Maybe project_dir is already the full projects subdir
        for p in Path(project_dir).rglob(filename):
            return p
        return None

    # Auto-detect: scan all project dirs
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None

    for proj in CLAUDE_PROJECTS_DIR.iterdir():
        if proj.is_dir():
            candidate = proj / filename
            if candidate.is_file():
                return candidate

    return None


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------


def parse_timestamp(ts_str):
    """Parse an ISO timestamp string into a datetime object."""
    if not ts_str:
        return None
    try:
        # Handle both 'Z' suffix and '+00:00'
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def extract_commit_message(command_str):
    """Extract the commit message from a git commit command string."""
    if not command_str or "git commit" not in command_str:
        return None

    # Try to extract from -m flag with heredoc pattern
    # Pattern: git commit -m "$(cat <<'EOF'\n<message>\nEOF\n)"
    heredoc_match = re.search(
        r"git commit.*?-m\s+\"\$\(cat <<'EOF'\n(.*?)\nEOF", command_str, re.DOTALL
    )
    if heredoc_match:
        msg = heredoc_match.group(1).strip()
        # Take just the first line as the message
        return msg.split("\n")[0].strip()

    # Pattern: git commit -m "message"
    quoted_match = re.search(r'git commit.*?-m\s+"([^"]+)"', command_str)
    if quoted_match:
        return quoted_match.group(1).split("\n")[0].strip()

    # Pattern: git commit -m 'message'
    single_match = re.search(r"git commit.*?-m\s+'([^']+)'", command_str)
    if single_match:
        return single_match.group(1).split("\n")[0].strip()

    return None


# Regex to extract total_tokens, tool_uses, duration_ms from <usage> tags
_USAGE_RE = re.compile(
    r"total_tokens:\s*(\d+).*?tool_uses:\s*(\d+).*?duration_ms:\s*(\d+)",
    re.DOTALL,
)


def _extract_subagent_usage(tool_use_id, result_text, task_tool_id_map, subagents):
    """Extract usage from a Task tool result and update the subagent."""
    if tool_use_id not in task_tool_id_map:
        return
    pseudo_id = task_tool_id_map[tool_use_id]
    if pseudo_id not in subagents:
        return
    match = _USAGE_RE.search(result_text)
    if match:
        subagents[pseudo_id]["tokens"]["total"] = int(match.group(1))
        subagents[pseudo_id]["tool_uses"] = int(match.group(2))
        subagents[pseudo_id]["duration_ms"] = int(match.group(3))


def _extract_task_notification_usage(content_str, subagents):
    """Extract usage from a <task-notification> string."""
    if "<task-notification>" not in content_str:
        return
    match = _USAGE_RE.search(content_str)
    if not match:
        return
    total = int(match.group(1))
    tools = int(match.group(2))
    dur = int(match.group(3))
    # Match by description from <summary>Agent "..." completed</summary>
    summary_match = re.search(r'Agent "(.+?)"', content_str)
    if not summary_match:
        return
    desc = summary_match.group(1)
    for sa in subagents.values():
        if sa.get("description", "").startswith(desc[:30]):
            sa["tokens"]["total"] = total
            sa["tool_uses"] = tools
            sa["duration_ms"] = dur
            break


def format_duration_ms(ms):
    """Format milliseconds as human-readable duration.

    >>> format_duration_ms(0)
    '0s'
    >>> format_duration_ms(45000)
    '45s'
    >>> format_duration_ms(120000)
    '2m'
    >>> format_duration_ms(3900000)
    '1h 5m'
    """
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def parse_session_jsonl(jsonl_path):
    """Parse a Claude Code JSONL session file and return structured stats.

    Returns a dict matching the output JSON schema.
    """
    models = defaultdict(
        lambda: {
            "messages": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        }
    )
    tool_counts = Counter()
    skill_invocations = Counter()
    subagents = {}  # agentId -> info dict
    task_tool_id_map = {}  # tool_use_id -> pseudo subagent id
    task_order = []  # sequential list of pseudo subagent ids
    commits = []
    timestamps = []

    session_id = None
    git_branch = None
    branch_counts = Counter()
    worktree_branches = set()

    with open(jsonl_path, "r") as f:
        for line_num, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                print(
                    f"WARNING: skipping malformed JSON at line {line_num}",
                    file=sys.stderr,
                )
                continue

            rec_type = record.get("type")

            # Extract session metadata from first user/assistant records
            if session_id is None and record.get("sessionId"):
                session_id = record["sessionId"]
            # Track all branches seen, with worktree branches preferred
            rec_branch = record.get("gitBranch")
            if rec_branch:
                branch_counts[rec_branch] += 1
                rec_cwd = record.get("cwd", "")
                if ".worktrees" in rec_cwd or ".worktree" in rec_cwd:
                    worktree_branches.add(rec_branch)

            # Collect timestamps from all records that have them
            ts = parse_timestamp(record.get("timestamp"))
            if ts:
                timestamps.append(ts)

            # --- Assistant records: model, usage, tool_use ---
            if rec_type == "assistant":
                message = record.get("message", {})
                model = message.get("model")
                usage = message.get("usage", {})
                agent_id = record.get("agentId")

                if model:
                    m = models[model]
                    m["messages"] += 1
                    m["input_tokens"] += usage.get("input_tokens", 0)
                    m["output_tokens"] += usage.get("output_tokens", 0)
                    m["cache_creation_tokens"] += usage.get(
                        "cache_creation_input_tokens", 0
                    )
                    m["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)

                # Track subagent tokens
                if agent_id and model:
                    if agent_id not in subagents:
                        subagents[agent_id] = {
                            "id": agent_id[:7] if len(agent_id) > 7 else agent_id,
                            "type": "unknown",
                            "model": model,
                            "tokens": {"total": 0},
                            "tool_uses": 0,
                            "duration_ms": 0,
                            "description": "",
                        }
                    sa = subagents[agent_id]
                    sa["tokens"]["total"] += usage.get("input_tokens", 0) + usage.get(
                        "output_tokens", 0
                    )

                # Parse tool_use content blocks
                content = message.get("content", [])
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue

                    tool_name = block.get("name", "unknown")
                    tool_counts[tool_name] += 1
                    tool_input = block.get("input", {})

                    # Skill invocations
                    if tool_name == "Skill":
                        skill_name = tool_input.get("skill", "unknown")
                        skill_invocations[skill_name] += 1

                    # Subagent launches via Task tool
                    if tool_name == "Task":
                        sub_type = tool_input.get("subagent_type", "unknown")
                        desc = tool_input.get("description", "")
                        sub_model = tool_input.get("model", "")
                        # Use a hash of the description as a pseudo-id
                        pseudo_id = f"task-{len(subagents)}"
                        subagents[pseudo_id] = {
                            "id": pseudo_id,
                            "type": sub_type,
                            "model": sub_model,
                            "tokens": {"total": 0},
                            "tool_uses": 0,
                            "duration_ms": 0,
                            "description": desc[:120],
                        }
                        # Track tool_use_id for matching results
                        tool_use_id = block.get("id", "")
                        if tool_use_id:
                            task_tool_id_map[tool_use_id] = pseudo_id
                        task_order.append(pseudo_id)

                    # Git commits via Bash
                    if tool_name == "Bash":
                        cmd = tool_input.get("command", "")
                        commit_msg = extract_commit_message(cmd)
                        if commit_msg:
                            commits.append({"message": commit_msg})

            # --- User records: parse Task tool results for subagent usage ---
            if rec_type == "user":
                msg_content = record.get("message", {})
                if isinstance(msg_content, dict):
                    user_content = msg_content.get("content", [])
                    if isinstance(user_content, list):
                        for uc in user_content:
                            if not isinstance(uc, dict):
                                continue
                            if uc.get("type") == "tool_result":
                                tool_use_id = uc.get("tool_use_id", "")
                                result_content = uc.get("content", "")
                                # content can be a list of blocks or a string
                                if isinstance(result_content, list):
                                    result_text = " ".join(
                                        str(b.get("text", ""))
                                        if isinstance(b, dict)
                                        else str(b)
                                        for b in result_content
                                    )
                                else:
                                    result_text = str(result_content)
                                _extract_subagent_usage(
                                    tool_use_id,
                                    result_text,
                                    task_tool_id_map,
                                    subagents,
                                )
                    elif isinstance(user_content, str):
                        # Task notifications come as string content
                        _extract_task_notification_usage(user_content, subagents)

    # --- Compute aggregates ---
    total_input = sum(m["input_tokens"] for m in models.values())
    total_output = sum(m["output_tokens"] for m in models.values())
    total_cache_creation = sum(m["cache_creation_tokens"] for m in models.values())
    total_cache_read = sum(m["cache_read_tokens"] for m in models.values())

    # Timestamps
    started_at = min(timestamps) if timestamps else None
    ended_at = max(timestamps) if timestamps else None
    duration_minutes = 0
    if started_at and ended_at:
        duration_minutes = round((ended_at - started_at).total_seconds() / 60)

    # Cost estimation
    estimated_cost = 0.0
    for model_name, m in models.items():
        pricing = MODEL_PRICING.get(model_name, FALLBACK_PRICING)
        cost = (
            m["input_tokens"] * pricing["input"] / 1_000_000
            + m["output_tokens"] * pricing["output"] / 1_000_000
            + m["cache_creation_tokens"] * pricing["cache_create"] / 1_000_000
            + m["cache_read_tokens"] * pricing["cache_read"] / 1_000_000
        )
        estimated_cost += cost

    # Build skills list
    skills_list = [
        {"skill": name, "count": count, "status": "unknown"}
        for name, count in skill_invocations.most_common()
    ]

    # Build subagents list
    subagents_list = list(subagents.values())

    # Deduplicate commits by message
    seen_commits = set()
    unique_commits = []
    for c in commits:
        if c["message"] not in seen_commits:
            seen_commits.add(c["message"])
            unique_commits.append(c)

    # Use provided session_id or derive from filename
    if not session_id:
        session_id = jsonl_path.stem

    session_id_short = session_id[:8] if session_id else "unknown"

    # Determine best branch: prefer worktree branches, then most-used
    if worktree_branches:
        # Pick the worktree branch with the most records
        git_branch = max(worktree_branches, key=lambda b: branch_counts.get(b, 0))
    elif branch_counts:
        git_branch = branch_counts.most_common(1)[0][0]

    # Collect all branches seen (for context)
    all_branches = sorted(branch_counts.keys()) if branch_counts else []

    return {
        "session_id": session_id,
        "session_id_short": session_id_short,
        "branch": git_branch or "",
        "all_branches": all_branches,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_minutes": duration_minutes,
        "models": {name: dict(data) for name, data in models.items()},
        "total_tokens": {
            "input": total_input,
            "output": total_output,
            "cache_creation": total_cache_creation,
            "cache_read": total_cache_read,
        },
        "tools": dict(tool_counts.most_common()),
        "skills_invoked": skills_list,
        "subagents": subagents_list,
        "commits": unique_commits,
        "problems_faced": [],
        "workflow_edges": {},
    }


# ---------------------------------------------------------------------------
# Phase: stats
# ---------------------------------------------------------------------------


def phase_stats(args):
    """Parse session JSONL and output structured stats JSON."""
    if not args.session_id:
        print("ERROR: --session-id is required for stats phase", file=sys.stderr)
        sys.exit(1)

    jsonl_path = find_session_jsonl(args.session_id, args.project_dir)
    if not jsonl_path:
        print(
            f"ERROR: session JSONL not found for {args.session_id}",
            file=sys.stderr,
        )
        print(
            f"Searched in: {args.project_dir or CLAUDE_PROJECTS_DIR}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Parsing: {jsonl_path}", file=sys.stderr)

    stats = parse_session_jsonl(jsonl_path)

    # Determine output path
    if args.stats_file:
        output_path = Path(args.stats_file)
    else:
        output_dir = Path(args.output_dir)
        output_path = output_dir / f"{stats['session_id_short']}-stats.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Stats written to: {output_path}", file=sys.stderr)

    # Print summary to stderr
    print(f"\n--- Session Summary ---", file=sys.stderr)
    print(f"Session:    {stats['session_id_short']}", file=sys.stderr)
    print(f"Branch:     {stats['branch']}", file=sys.stderr)
    print(f"Duration:   {stats['duration_minutes']} minutes", file=sys.stderr)
    print(f"Models:     {', '.join(stats['models'].keys())}", file=sys.stderr)
    total = stats["total_tokens"]
    print(
        f"Tokens:     {total['input']:,} in / {total['output']:,} out / "
        f"{total['cache_creation']:,} cache-create / {total['cache_read']:,} cache-read",
        file=sys.stderr,
    )
    print(
        f"Tools:      {sum(stats['tools'].values())} calls across {len(stats['tools'])} tools",
        file=sys.stderr,
    )
    if stats["skills_invoked"]:
        print(
            f"Skills:     {', '.join(s['skill'] for s in stats['skills_invoked'])}",
            file=sys.stderr,
        )
    if stats["subagents"]:
        print(f"Subagents:  {len(stats['subagents'])} launched", file=sys.stderr)
    if stats["commits"]:
        print(f"Commits:    {len(stats['commits'])}", file=sys.stderr)

    # Also print JSON to stdout for piping
    print(json.dumps(stats, indent=2))

    return stats


# ---------------------------------------------------------------------------
# Phase: mermaid - annotated workflow diagrams
# ---------------------------------------------------------------------------

# Keywords in edge labels that indicate failure paths
FAILURE_KEYWORDS = re.compile(
    r"fail|error|stuck|reject|crash|timeout|broken|"
    r"changes needed|issues|no\b|can.t|cannot|inconclusive|"
    r"3\+\s*failures",
    re.IGNORECASE,
)

# Edge / node colors for mermaid annotation
COLOR_GREEN = "#4CAF50"  # traversed successfully
COLOR_RED = "#F44336"  # error/failure path traversed
COLOR_GREY = "#9E9E9E"  # not traversed (unused)

NODE_STYLE_USED = "fill:#C8E6C9,stroke:#4CAF50,stroke-width:3px"

# Regex pattern for mermaid edges (reused from tdd-debug-diagram.py)
EDGE_PATTERN = re.compile(
    r"(\b[A-Z][A-Z0-9_]*\b)\s*(--[->.]*)(\|([^|]*)\|)?\s*(\b[A-Z][A-Z0-9_]*\b)"
)


def extract_mermaid_from_skill(skill_path):
    """Extract the first mermaid code block from a SKILL.md file.

    Returns the mermaid content as a string, or None if not found.
    """
    if not os.path.isfile(skill_path):
        return None

    with open(skill_path, "r") as f:
        content = f.read()

    # Match ```mermaid ... ``` block
    match = re.search(r"```mermaid\s*\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def find_skill_workflow(skill_name, skills_dir):
    """Find and return a workflow mermaid template for a skill.

    Search order:
    1. <skills_dir>/<skill_name>/SKILL.md
    2. If skill has colon notation (e.g., tdd:ci), try parent: <skills_dir>/tdd/SKILL.md
    """
    skills_path = Path(skills_dir)

    # Try exact skill directory first
    exact_path = skills_path / skill_name / "SKILL.md"
    mermaid = extract_mermaid_from_skill(str(exact_path))
    if mermaid:
        return mermaid

    # Try parent skill (for colon notation like tdd:ci -> tdd)
    if ":" in skill_name:
        parent = skill_name.split(":")[0]
        parent_path = skills_path / parent / "SKILL.md"
        mermaid = extract_mermaid_from_skill(str(parent_path))
        if mermaid:
            return mermaid

    return None


def find_edges(lines):
    """Parse edges from mermaid lines.

    Returns list of dicts: {index, line, src, dst, label, is_failure}
    Reuses the pattern from tdd-debug-diagram.py.
    """
    edges = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("classDef", "style", "%%", "linkStyle")):
            continue
        m = EDGE_PATTERN.search(line)
        if m:
            label = m.group(4) or ""
            label_clean = label.strip().strip('"')
            is_failure = bool(FAILURE_KEYWORDS.search(label_clean))
            edges.append(
                {
                    "index": len(edges),
                    "line": i,
                    "src": m.group(1),
                    "dst": m.group(5),
                    "label": label_clean,
                    "is_failure": is_failure,
                }
            )
    return edges


def annotate_mermaid(template, edge_counts, used_nodes):
    """Apply colors and traversal counters to a mermaid template.

    Args:
        template: mermaid diagram string
        edge_counts: dict mapping "SRC->DST" -> count
        used_nodes: set of node IDs that were used (appear in traversed edges
                    or were invoked as skills)

    Returns:
        Annotated mermaid string with colored edges, counters, and node styles.
    """
    lines = template.splitlines()

    # Parse edges from the template
    edges = find_edges(lines)

    # Build set of traversed edge pairs
    traversed = set()
    for edge_key, count in edge_counts.items():
        if count > 0 and "->" in edge_key:
            parts = edge_key.split("->")
            if len(parts) == 2:
                traversed.add((parts[0].strip(), parts[1].strip()))

    # Update edge labels with traversal counts
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
                    line[: m.start()]
                    + m.group(1)
                    + m.group(2)
                    + new_label
                    + line[m.start(4) :]
                )
                lines[i] = new_line
                break

    # Build linkStyle directives to color edges
    link_styles = []
    for edge in edges:
        key = (edge["src"], edge["dst"])
        if key in traversed:
            color = COLOR_RED if edge["is_failure"] else COLOR_GREEN
        else:
            color = COLOR_GREY

        link_styles.append(
            f"    linkStyle {edge['index']} stroke:{color},stroke-width:2px"
        )

    # Build style directives for used nodes
    node_styles = []
    for node_id in sorted(used_nodes):
        # Check the node actually appears in the template
        node_in_template = any(
            re.search(rf"\b{re.escape(node_id)}\b", line)
            for line in lines
            if not line.strip().startswith(("classDef", "style", "%%", "linkStyle"))
        )
        if node_in_template:
            node_styles.append(f"    style {node_id} {NODE_STYLE_USED}")

    # Insert linkStyle and node style directives before classDef lines
    insert_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith(("classDef", "style ")):
            insert_idx = i
            break

    for j, style in enumerate(link_styles + node_styles):
        lines.insert(insert_idx + j, style)

    return "\n".join(lines)


def phase_mermaid(args):
    """Generate annotated mermaid workflow diagrams from session stats."""
    if not args.stats_file:
        print("ERROR: --stats-file is required for mermaid phase", file=sys.stderr)
        sys.exit(1)

    stats_path = Path(args.stats_file)
    if not stats_path.is_file():
        print(f"ERROR: stats file not found: {stats_path}", file=sys.stderr)
        sys.exit(1)

    with open(stats_path) as f:
        stats = json.load(f)

    # Determine skills directory
    if args.skills_dir:
        skills_dir = args.skills_dir
    else:
        # Try to infer from the script location
        script_dir = Path(__file__).resolve().parent
        skills_dir = str(script_dir.parent / "skills")

    if not os.path.isdir(skills_dir):
        print(f"WARNING: skills directory not found: {skills_dir}", file=sys.stderr)

    # Collect skills to process: skills_invoked + skills from workflow_edges
    skill_names = set()
    for s in stats.get("skills_invoked", []):
        skill_names.add(s["skill"])

    workflow_edges = stats.get("workflow_edges", {})
    # workflow_edges might be keyed by skill name
    for skill_key in workflow_edges:
        skill_names.add(skill_key)

    # Also collect any skill-like names from edge keys in workflow_edges
    # (workflow_edges can be flat: {"SRC->DST": count} or nested: {"skill": {"SRC->DST": count}})
    flat_edges = {}
    nested_edges = {}
    for key, value in workflow_edges.items():
        if isinstance(value, dict):
            nested_edges[key] = value
        elif isinstance(value, (int, float)):
            flat_edges[key] = int(value)

    diagrams = {}

    for skill_name in skill_names:
        template = find_skill_workflow(skill_name, skills_dir)
        if not template:
            print(
                f"  No workflow template found for skill: {skill_name}",
                file=sys.stderr,
            )
            continue

        # Get edge counts for this skill
        edge_counts = nested_edges.get(skill_name, flat_edges)

        # Collect used nodes from traversed edges
        used_nodes = set()
        for edge_key, count in edge_counts.items():
            if count > 0 and "->" in edge_key:
                parts = edge_key.split("->")
                if len(parts) == 2:
                    used_nodes.add(parts[0].strip())
                    used_nodes.add(parts[1].strip())

        # Also mark the skill itself as a used node if it appears
        # (e.g., TDDCI node for tdd:ci skill)
        used_nodes.add(skill_name.upper().replace(":", ""))

        annotated = annotate_mermaid(template, edge_counts, used_nodes)
        diagrams[skill_name] = annotated
        print(f"  Generated diagram for: {skill_name}", file=sys.stderr)

    # Write diagrams.json next to the stats file
    output_path = stats_path.parent / (
        stats_path.stem.replace("-stats", "") + "-diagrams.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(diagrams, f, indent=2)

    print(f"Diagrams written to: {output_path}", file=sys.stderr)
    print(f"Skills processed: {len(diagrams)}/{len(skill_names)}", file=sys.stderr)

    # Also print JSON to stdout for piping
    print(json.dumps(diagrams, indent=2))

    return diagrams


# ---------------------------------------------------------------------------
# Comment / Summary formatting helpers
# ---------------------------------------------------------------------------


def format_duration(minutes):
    """Format minutes as Xh Ym.

    >>> format_duration(0)
    '0m'
    >>> format_duration(45)
    '45m'
    >>> format_duration(78)
    '1h 18m'
    >>> format_duration(120)
    '2h 0m'
    """
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def format_tokens(n):
    """Format token count with K/M suffix.

    >>> format_tokens(500)
    '500'
    >>> format_tokens(1500)
    '1.5K'
    >>> format_tokens(25000)
    '25.0K'
    >>> format_tokens(1500000)
    '1.5M'
    """
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def estimate_cost_for_model(model_name, tokens):
    """Estimate cost for a single model given its token counts.

    Args:
        model_name: Model identifier string.
        tokens: Dict with input_tokens, output_tokens, cache_creation_tokens,
                cache_read_tokens.

    Returns:
        Cost in USD (float).
    """
    pricing = MODEL_PRICING.get(model_name, FALLBACK_PRICING)
    return (
        tokens.get("input_tokens", 0) * pricing["input"] / 1_000_000
        + tokens.get("output_tokens", 0) * pricing["output"] / 1_000_000
        + tokens.get("cache_creation_tokens", 0) * pricing["cache_create"] / 1_000_000
        + tokens.get("cache_read_tokens", 0) * pricing["cache_read"] / 1_000_000
    )


def _session_marker(session_id):
    """Build the hidden comment marker for a session (first 16 chars)."""
    short = session_id[:16] if session_id else "unknown"
    return f"{SESSION_MARKER_PREFIX}{short} -->"


def format_session_comment(stats, diagrams=None):
    """Format session stats as a GitHub comment markdown body.

    The comment contains a hidden marker, TL;DR, tables, collapsible
    sections, and embedded JSON for machine parsing.
    """
    sid = stats.get("session_id", "unknown")
    sid_short = stats.get("session_id_short", sid[:8])
    branch = stats.get("branch", "")
    duration = stats.get("duration_minutes", 0)
    commits = stats.get("commits", [])
    skills = stats.get("skills_invoked", [])
    subagents = stats.get("subagents", [])
    tools = stats.get("tools", {})
    models = stats.get("models", {})
    problems = stats.get("problems_faced", [])

    # Primary model name (short form for TL;DR)
    primary_model = ""
    if models:
        # Pick the model with the most messages
        primary_model = max(models, key=lambda m: models[m].get("messages", 0))
        # Shorten: claude-opus-4-5-20251101 -> opus-4-5
        pm = primary_model
        pm = re.sub(r"^claude-", "", pm)
        pm = re.sub(r"-\d{8}$", "", pm)
        primary_model = pm

    # Skills list for TL;DR
    skills_str = ", ".join(s["skill"] for s in skills) if skills else ""

    lines = []

    # Hidden marker
    lines.append(_session_marker(sid))
    lines.append("")

    # TL;DR
    tldr_parts = [f"Session `{sid_short}`"]
    if primary_model:
        tldr_parts.append(primary_model)
    tldr_parts.append(format_duration(duration))
    tldr_parts.append(f"{len(commits)} commit{'s' if len(commits) != 1 else ''}")
    if skills_str:
        tldr_parts.append(skills_str)
    lines.append(f"**TL;DR:** {' | '.join(tldr_parts)}")
    lines.append("")

    # Header
    lines.append(f"### Session `{sid_short}`")
    lines.append("")
    lines.append(f"- **Session ID:** `{sid}`")
    lines.append(f"- **Branch:** `{branch}`")
    lines.append(f"- **Duration:** {format_duration(duration)}")
    if stats.get("started_at"):
        lines.append(f"- **Started:** {stats['started_at']}")
    if stats.get("ended_at"):
        lines.append(f"- **Ended:** {stats['ended_at']}")
    lines.append("")

    # Token usage table (per-model)
    lines.append("#### Token Usage")
    lines.append("")
    lines.append("| Model | Input | Output | Cache Create | Cache Read |")
    lines.append("|-------|------:|-------:|-------------:|-----------:|")

    for model_name, m in models.items():
        short_model = re.sub(r"^claude-", "", model_name)
        short_model = re.sub(r"-\d{8}$", "", short_model)
        lines.append(
            f"| {short_model} "
            f"| {format_tokens(m.get('input_tokens', 0))} "
            f"| {format_tokens(m.get('output_tokens', 0))} "
            f"| {format_tokens(m.get('cache_creation_tokens', 0))} "
            f"| {format_tokens(m.get('cache_read_tokens', 0))} |"
        )

    total = stats.get("total_tokens", {})
    lines.append(
        f"| **Total** "
        f"| **{format_tokens(total.get('input', 0))}** "
        f"| **{format_tokens(total.get('output', 0))}** "
        f"| **{format_tokens(total.get('cache_creation', 0))}** "
        f"| **{format_tokens(total.get('cache_read', 0))}** |"
    )
    lines.append("")

    # Subagents table
    if subagents:
        lines.append("#### Subagents")
        lines.append("")
        lines.append("| ID | Type | Model | Total Tokens | Tool Uses | Duration |")
        lines.append("|----|------|-------|-------------:|----------:|---------:|")
        for sa in subagents:
            sa_model = sa.get("model", "")
            sa_model_short = re.sub(r"^claude-", "", sa_model) if sa_model else "-"
            sa_model_short = (
                re.sub(r"-\d{8}$", "", sa_model_short) if sa_model_short != "-" else "-"
            )
            sa_duration = sa.get("duration_ms", 0)
            lines.append(
                f"| {sa.get('id', '')} "
                f"| {sa.get('type', '')} "
                f"| {sa_model_short} "
                f"| {format_tokens(sa.get('tokens', {}).get('total', 0))} "
                f"| {sa.get('tool_uses', 0)} "
                f"| {format_duration_ms(sa_duration) if sa_duration else '-'} |"
            )
        lines.append("")

    # Skills table
    if skills:
        lines.append("#### Skills")
        lines.append("")
        lines.append("| Skill | Invocations | Status |")
        lines.append("|-------|------------:|--------|")
        for s in skills:
            lines.append(
                f"| {s['skill']} | {s.get('count', 1)} | {s.get('status', 'unknown')} |"
            )
        lines.append("")

    # Tool usage (collapsible)
    if tools:
        lines.append("<details>")
        lines.append("<summary>Tool Usage</summary>")
        lines.append("")
        lines.append("| Tool | Count |")
        lines.append("|------|------:|")
        # Sort by count descending
        for tool_name, count in sorted(tools.items(), key=lambda x: -x[1]):
            lines.append(f"| {tool_name} | {count} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Workflow diagrams (mermaid)
    if diagrams:
        lines.append("#### Workflow Diagrams")
        lines.append("")
        for diagram_name, mermaid_src in diagrams.items():
            lines.append(f"**{diagram_name}**")
            lines.append("")
            lines.append("```mermaid")
            lines.append(mermaid_src)
            lines.append("```")
            lines.append("")

    # Problems faced
    if problems:
        lines.append("#### Problems Faced")
        lines.append("")
        lines.append("| # | Problem |")
        lines.append("|---|---------|")
        for i, problem in enumerate(problems, 1):
            p_text = problem if isinstance(problem, str) else str(problem)
            lines.append(f"| {i} | {p_text} |")
        lines.append("")

    # Commits
    if commits:
        lines.append("#### Commits")
        lines.append("")
        for c in commits:
            lines.append(f"- {c.get('message', '(no message)')}")
        lines.append("")

    # Session Data JSON (collapsible)
    lines.append("<details>")
    lines.append("<summary>Session Data (JSON)</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(stats, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("</details>")

    return "\n".join(lines)


def parse_session_data_from_comment(comment_body):
    """Extract JSON from a comment's collapsible Session Data block.

    Looks for the pattern:
      <details>
      <summary>Session Data (JSON)</summary>
      ```json
      { ... }
      ```
      </details>

    Returns parsed dict or None if not found/parseable.
    """
    pattern = re.compile(
        r"<details>\s*\n"
        r"<summary>Session Data \(JSON\)</summary>\s*\n+"
        r"```json\s*\n"
        r"(.*?)"
        r"\n```",
        re.DOTALL,
    )
    m = pattern.search(comment_body)
    if not m:
        return None

    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def format_summary_comment(sessions):
    """Format pinned summary from list of session stats dicts.

    Always recalculates totals from the provided session data.
    """
    lines = []

    # Marker
    lines.append(SUMMARY_MARKER)
    lines.append("")

    # Aggregate totals
    total_input = sum(s.get("total_tokens", {}).get("input", 0) for s in sessions)
    total_output = sum(s.get("total_tokens", {}).get("output", 0) for s in sessions)
    total_cache_create = sum(
        s.get("total_tokens", {}).get("cache_creation", 0) for s in sessions
    )
    total_cache_read = sum(
        s.get("total_tokens", {}).get("cache_read", 0) for s in sessions
    )
    total_commits = sum(len(s.get("commits", [])) for s in sessions)
    total_duration = sum(s.get("duration_minutes", 0) for s in sessions)

    # TL;DR
    lines.append(
        f"**TL;DR:** {len(sessions)} sessions | "
        f"{format_duration(total_duration)} | "
        f"{total_commits} commits"
    )
    lines.append("")

    # Header
    lines.append("### Session Summary")
    lines.append("")

    # Aggregate token usage table
    lines.append("#### Aggregate Token Usage")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| Sessions | {len(sessions)} |")
    lines.append(f"| Total Duration | {format_duration(total_duration)} |")
    lines.append(f"| Input Tokens | {format_tokens(total_input)} |")
    lines.append(f"| Output Tokens | {format_tokens(total_output)} |")
    lines.append(f"| Cache Create Tokens | {format_tokens(total_cache_create)} |")
    lines.append(f"| Cache Read Tokens | {format_tokens(total_cache_read)} |")
    lines.append(f"| Total Commits | {total_commits} |")
    lines.append("")

    # Session history table
    lines.append("#### Session History")
    lines.append("")
    lines.append("| Session | Branch | Duration | Input | Output | Commits |")
    lines.append("|---------|--------|----------|------:|-------:|--------:|")

    for s in sessions:
        sid_short = s.get("session_id_short", s.get("session_id", "?")[:8])
        branch = s.get("branch", "")
        dur = format_duration(s.get("duration_minutes", 0))
        inp = format_tokens(s.get("total_tokens", {}).get("input", 0))
        out = format_tokens(s.get("total_tokens", {}).get("output", 0))
        n_commits = len(s.get("commits", []))
        lines.append(
            f"| `{sid_short}` | `{branch}` | {dur} | {inp} | {out} | {n_commits} |"
        )
    lines.append("")

    # Totals verification
    lines.append("#### Totals Verification")
    lines.append("")
    lines.append(
        f"Sum of session commits: "
        + " + ".join(str(len(s.get("commits", []))) for s in sessions)
        + f" = **{total_commits}**"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub API helpers (via gh CLI)
# ---------------------------------------------------------------------------


def gh_find_comment(repo, number, marker):
    """Find comment ID by marker text using gh CLI.

    Returns comment ID (int) or None if not found.
    """
    import subprocess

    cmd = [
        "gh",
        "api",
        f"repos/{repo}/issues/{number}/comments",
        "--paginate",
        "--jq",
        f'.[] | select(.body | contains("{marker}")) | .id',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            # May have multiple lines if multiple matches; take first
            first_id = result.stdout.strip().split("\n")[0]
            return int(first_id)
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
        print(f"WARNING: gh_find_comment failed: {e}", file=sys.stderr)
    return None


def gh_post_comment(repo, number, body):
    """Post new comment to a PR/issue, return comment ID."""
    import subprocess

    cmd = [
        "gh",
        "api",
        f"repos/{repo}/issues/{number}/comments",
        "-f",
        f"body={body}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            resp = json.loads(result.stdout)
            comment_id = resp.get("id")
            print(f"Posted comment #{comment_id}", file=sys.stderr)
            return comment_id
        else:
            print(f"ERROR posting comment: {result.stderr}", file=sys.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR posting comment: {e}", file=sys.stderr)
    return None


def gh_update_comment(repo, comment_id, body):
    """Update existing comment."""
    import subprocess

    cmd = [
        "gh",
        "api",
        f"repos/{repo}/issues/comments/{comment_id}",
        "-X",
        "PATCH",
        "-f",
        f"body={body}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"Updated comment #{comment_id}", file=sys.stderr)
            return True
        else:
            print(f"ERROR updating comment: {result.stderr}", file=sys.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"ERROR updating comment: {e}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Phase: comment - Post/update per-session GitHub comment
# ---------------------------------------------------------------------------


def phase_comment(args):
    """Post or update a per-session comment on a GitHub PR/issue."""
    if not args.stats_file:
        print("ERROR: --stats-file is required for comment phase", file=sys.stderr)
        sys.exit(1)

    stats_path = Path(args.stats_file)
    if not stats_path.is_file():
        print(f"ERROR: stats file not found: {stats_path}", file=sys.stderr)
        sys.exit(1)

    with open(stats_path) as f:
        stats = json.load(f)

    # Load diagrams if available
    diagrams = None
    if args.diagrams_file:
        diagrams_path = Path(args.diagrams_file)
        if diagrams_path.is_file():
            with open(diagrams_path) as f:
                diagrams = json.load(f)
            print(f"Loaded diagrams from: {diagrams_path}", file=sys.stderr)
    else:
        # Auto-detect diagrams file next to stats file
        auto_diagrams = stats_path.parent / (
            stats_path.stem.replace("-stats", "") + "-diagrams.json"
        )
        if auto_diagrams.is_file():
            with open(auto_diagrams) as f:
                diagrams = json.load(f)
            print(f"Auto-loaded diagrams from: {auto_diagrams}", file=sys.stderr)

    # Also try diagrams.json in same directory
    if diagrams is None:
        fallback_diagrams = stats_path.parent / "diagrams.json"
        if fallback_diagrams.is_file():
            with open(fallback_diagrams) as f:
                diagrams = json.load(f)
            print(f"Auto-loaded diagrams from: {fallback_diagrams}", file=sys.stderr)

    body = format_session_comment(stats, diagrams)

    if getattr(args, "dry_run", False):
        print("--- DRY RUN: Comment body ---", file=sys.stderr)
        print(body)
        return body

    # Validate required args for posting
    if not args.repo or not args.number:
        print(
            "ERROR: --repo and --number are required for posting (or use --dry-run)",
            file=sys.stderr,
        )
        sys.exit(1)

    marker = _session_marker(stats.get("session_id", "unknown"))
    existing_id = gh_find_comment(args.repo, args.number, marker)

    if existing_id:
        print(f"Found existing comment #{existing_id}, updating...", file=sys.stderr)
        gh_update_comment(args.repo, existing_id, body)
    else:
        print("No existing comment found, creating new...", file=sys.stderr)
        gh_post_comment(args.repo, args.number, body)

    return body


# ---------------------------------------------------------------------------
# Phase: summary - Post/update pinned summary comment
# ---------------------------------------------------------------------------


def phase_summary(args):
    """Post or update a pinned summary comment that recalculates from session comments."""
    if not args.repo or not args.number:
        if getattr(args, "dry_run", False):
            print(
                "ERROR: --repo and --number are required even for dry-run summary",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            "ERROR: --repo and --number are required for summary phase",
            file=sys.stderr,
        )
        sys.exit(1)

    import subprocess

    # Fetch all comments on the PR/issue
    cmd = [
        "gh",
        "api",
        f"repos/{args.repo}/issues/{args.number}/comments",
        "--paginate",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"ERROR fetching comments: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        all_comments = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR fetching comments: {e}", file=sys.stderr)
        sys.exit(1)

    # Find session comments (have SESSION marker but NOT SUMMARY marker)
    sessions = []
    for comment in all_comments:
        body = comment.get("body", "")
        if SESSION_MARKER_PREFIX in body and SUMMARY_MARKER not in body:
            data = parse_session_data_from_comment(body)
            if data:
                sessions.append(data)
            else:
                print(
                    f"WARNING: Could not parse session data from comment #{comment.get('id')}",
                    file=sys.stderr,
                )

    if not sessions:
        print("No session comments found, nothing to summarize.", file=sys.stderr)
        return None

    print(f"Found {len(sessions)} session comment(s)", file=sys.stderr)

    body = format_summary_comment(sessions)

    if getattr(args, "dry_run", False):
        print("--- DRY RUN: Summary body ---", file=sys.stderr)
        print(body)
        return body

    # Find existing summary comment
    existing_id = gh_find_comment(args.repo, args.number, SUMMARY_MARKER)

    if existing_id:
        print(
            f"Found existing summary comment #{existing_id}, updating...",
            file=sys.stderr,
        )
        gh_update_comment(args.repo, existing_id, body)
    else:
        print("No existing summary comment found, creating new...", file=sys.stderr)
        gh_post_comment(args.repo, args.number, body)

    return body


# ---------------------------------------------------------------------------
# Phase: extract - Export session data from PR/issue comments to CSV/MD/HTML
# ---------------------------------------------------------------------------

# CSV columns for the extract output
EXTRACT_CSV_COLUMNS = [
    "pr_number",
    "target_type",
    "pr_title",
    "pr_author",
    "pr_status",
    "session_id",
    "session_started",
    "session_duration_min",
    "models_used",
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_create",
    "total_cache_read",
    "estimated_cost_usd",
    "commits_count",
    "commit_shas",
    "skills_used",
    "per_skill_tokens",
    "subagent_count",
    "per_subagent_tokens",
    "problems_count",
    "problems_resolved",
    "lines_added",
    "lines_removed",
    "time_to_merge_hours",
    "acceptance_status",
]


def _gh_list_items(repo, item_type, from_date=None, to_date=None):
    """List PRs or issues via gh CLI.

    Args:
        repo: OWNER/NAME
        item_type: 'pr' or 'issue'
        from_date: YYYY-MM-DD start date filter (optional)
        to_date: YYYY-MM-DD end date filter (optional)

    Returns:
        List of dicts with number, title, author, state, etc.
    """
    import subprocess

    if item_type == "pr":
        cmd = [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,title,author,state,additions,deletions,createdAt,mergedAt,closedAt",
        ]
    else:
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,title,author,state,createdAt,closedAt",
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(
                f"WARNING: gh {item_type} list failed: {result.stderr}", file=sys.stderr
            )
            return []
        items = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: gh {item_type} list failed: {e}", file=sys.stderr)
        return []

    # Filter by date range if specified
    if from_date or to_date:
        filtered = []
        for item in items:
            created = item.get("createdAt", "")
            if created:
                created_date = created[:10]  # YYYY-MM-DD
                if from_date and created_date < from_date:
                    continue
                if to_date and created_date > to_date:
                    continue
            filtered.append(item)
        return filtered

    return items


def _gh_fetch_comments(repo, number):
    """Fetch all comments for a PR/issue number.

    Returns list of comment dicts with 'body' field.
    """
    import subprocess

    cmd = [
        "gh",
        "api",
        f"repos/{repo}/issues/{number}/comments",
        "--paginate",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(
                f"WARNING: fetch comments for #{number} failed: {result.stderr}",
                file=sys.stderr,
            )
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: fetch comments for #{number} failed: {e}", file=sys.stderr)
        return []


def _compute_pr_status(item, item_type):
    """Compute pr_status and acceptance_status from GH API item.

    Returns (pr_status, acceptance_status).
    """
    if item_type == "pr":
        state = item.get("state", "").upper()
        if state == "MERGED":
            return "merged", "merged"
        elif state == "CLOSED":
            return "closed", "closed"
        else:
            return "open", "open"
    else:
        state = item.get("state", "").upper()
        if state == "CLOSED":
            return "closed", "closed"
        else:
            return "open", "open"


def _compute_time_to_merge(item, item_type):
    """Compute hours from creation to merge for PRs.

    Returns float hours or empty string if not merged.
    """
    if item_type != "pr":
        return ""
    merged_at = item.get("mergedAt")
    created_at = item.get("createdAt")
    if not merged_at or not created_at:
        return ""
    try:
        merged = parse_timestamp(merged_at)
        created = parse_timestamp(created_at)
        if merged and created:
            return round((merged - created).total_seconds() / 3600, 1)
    except Exception:
        pass
    return ""


def _build_extract_row(item, item_type, session_data):
    """Build a single CSV row dict from GH item metadata + parsed session data.

    Args:
        item: GH API item dict (PR or issue)
        item_type: 'pr' or 'issue'
        session_data: Parsed session JSON from comment

    Returns:
        Dict with keys matching EXTRACT_CSV_COLUMNS.
    """
    pr_status, acceptance_status = _compute_pr_status(item, item_type)

    # Extract fields from session data
    models = session_data.get("models", {})
    models_used = ",".join(sorted(models.keys()))

    total_tokens = session_data.get("total_tokens", {})

    commits = session_data.get("commits", [])
    commit_shas = ";".join(c.get("sha", c.get("message", "")[:7]) for c in commits)

    skills = session_data.get("skills_invoked", [])
    skills_used = ",".join(s.get("skill", "") for s in skills)

    # Per-skill tokens: build from skills + models (approximate)
    per_skill = {}
    for s in skills:
        skill_name = s.get("skill", "")
        per_skill[skill_name] = {"in": 0, "out": 0}
    per_skill_str = json.dumps(per_skill) if per_skill else ""

    subagents = session_data.get("subagents", [])
    per_subagent = {}
    for sa in subagents:
        sa_type = sa.get("type", "unknown")
        tokens = sa.get("tokens", {})
        total = tokens.get("total", 0)
        if sa_type in per_subagent:
            per_subagent[sa_type]["total"] += total
        else:
            per_subagent[sa_type] = {"total": total}
    per_subagent_str = json.dumps(per_subagent) if per_subagent else ""

    problems = session_data.get("problems_faced", [])

    # Author handling (gh pr list returns {login: ...}, gh issue list too)
    author = item.get("author", {})
    if isinstance(author, dict):
        author_login = author.get("login", "")
    else:
        author_login = str(author)

    return {
        "pr_number": item.get("number", ""),
        "target_type": item_type,
        "pr_title": item.get("title", ""),
        "pr_author": author_login,
        "pr_status": pr_status,
        "session_id": session_data.get("session_id", ""),
        "session_started": session_data.get("started_at", ""),
        "session_duration_min": session_data.get("duration_minutes", 0),
        "models_used": models_used,
        "total_input_tokens": total_tokens.get("input", 0),
        "total_output_tokens": total_tokens.get("output", 0),
        "total_cache_create": total_tokens.get("cache_creation", 0),
        "total_cache_read": total_tokens.get("cache_read", 0),
        "estimated_cost_usd": session_data.get("estimated_cost_usd", 0.0),
        "commits_count": len(commits),
        "commit_shas": commit_shas,
        "skills_used": skills_used,
        "per_skill_tokens": per_skill_str,
        "subagent_count": len(subagents),
        "per_subagent_tokens": per_subagent_str,
        "problems_count": len(problems),
        "problems_resolved": len(
            [p for p in problems if isinstance(p, dict) and p.get("resolved")]
        ),
        "lines_added": item.get("additions", ""),
        "lines_removed": item.get("deletions", ""),
        "time_to_merge_hours": _compute_time_to_merge(item, item_type),
        "acceptance_status": acceptance_status,
    }


def write_csv(rows, path):
    """Write extract rows to CSV file.

    Args:
        rows: List of dicts with EXTRACT_CSV_COLUMNS keys.
        path: Output file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXTRACT_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_md_report(rows, path, args):
    """Write markdown analytics report.

    Args:
        rows: List of dicts with EXTRACT_CSV_COLUMNS keys.
        path: Output file path.
        args: CLI args (for repo, from_date, to_date).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    repo = getattr(args, "repo", "") or "unknown"
    from_date = getattr(args, "from_date", "") or "start"
    to_date = getattr(args, "to_date", "") or "now"

    # Compute summary metrics
    pr_rows = [r for r in rows if r.get("target_type") == "pr"]
    issue_rows = [r for r in rows if r.get("target_type") == "issue"]
    total_sessions = len(rows)
    total_cost = sum(float(r.get("estimated_cost_usd", 0)) for r in rows)
    avg_cost = total_cost / total_sessions if total_sessions else 0

    # Unique PRs/issues
    unique_prs = set(r["pr_number"] for r in pr_rows)
    unique_issues = set(r["pr_number"] for r in issue_rows)

    # PR acceptance rate
    merged_prs = set(
        r["pr_number"] for r in pr_rows if r.get("acceptance_status") == "merged"
    )
    closed_prs = set(
        r["pr_number"]
        for r in pr_rows
        if r.get("acceptance_status") in ("merged", "closed")
    )
    acceptance_rate = (len(merged_prs) / len(closed_prs) * 100) if closed_prs else 0

    lines = []
    lines.append("# Claude Code Analytics Report")
    lines.append("")
    lines.append(f"**Period:** {from_date} to {to_date}")
    lines.append(f"**Repository:** {repo}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| PRs with session data | {len(unique_prs)} |")
    lines.append(f"| Issues with session data | {len(unique_issues)} |")
    lines.append(f"| Total sessions | {total_sessions} |")
    lines.append(f"| Total cost | ${total_cost:.2f} |")
    lines.append(f"| Average cost per session | ${avg_cost:.2f} |")
    lines.append(f"| PR acceptance rate | {acceptance_rate:.0f}% |")
    lines.append("")

    # Per-PR/issue breakdown
    lines.append("## Per-PR Breakdown")
    lines.append("")
    lines.append("| # | Type | Title | Author | Status | Sessions | Cost | Commits |")
    lines.append("|---|------|-------|--------|--------|----------|------|---------|")

    # Group rows by pr_number
    by_number = defaultdict(list)
    for r in rows:
        by_number[r["pr_number"]].append(r)

    for num in sorted(
        by_number.keys(), key=lambda x: int(x) if str(x).isdigit() else 0
    ):
        group = by_number[num]
        first = group[0]
        group_cost = sum(float(r.get("estimated_cost_usd", 0)) for r in group)
        group_commits = sum(int(r.get("commits_count", 0)) for r in group)
        lines.append(
            f"| {num} "
            f"| {first.get('target_type', '')} "
            f"| {first.get('pr_title', '')[:50]} "
            f"| {first.get('pr_author', '')} "
            f"| {first.get('pr_status', '')} "
            f"| {len(group)} "
            f"| ${group_cost:.2f} "
            f"| {group_commits} |"
        )
    lines.append("")

    # Model usage distribution
    lines.append("## Model Usage Distribution")
    lines.append("")
    lines.append("| Model | Session Count |")
    lines.append("|-------|--------------|")

    model_counts = Counter()
    for r in rows:
        models = r.get("models_used", "")
        if models:
            for m in models.split(","):
                m = m.strip()
                if m:
                    model_counts[m] += 1

    for model, count in model_counts.most_common():
        lines.append(f"| {model} | {count} |")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_html_dashboard(rows, path, args):
    """Write HTML dashboard with Chart.js charts.

    Args:
        rows: List of dicts with EXTRACT_CSV_COLUMNS keys.
        path: Output file path.
        args: CLI args (for repo, from_date, to_date).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    repo = getattr(args, "repo", "") or "unknown"
    from_date = getattr(args, "from_date", "") or "start"
    to_date = getattr(args, "to_date", "") or "now"

    # Compute stats for cards
    total_sessions = len(rows)
    total_cost = sum(float(r.get("estimated_cost_usd", 0)) for r in rows)
    unique_numbers = set(r["pr_number"] for r in rows)
    total_prs_issues = len(unique_numbers)
    total_commits = sum(int(r.get("commits_count", 0)) for r in rows)

    # Cost per PR data
    cost_by_pr = defaultdict(float)
    for r in rows:
        label = f"#{r['pr_number']}"
        cost_by_pr[label] += float(r.get("estimated_cost_usd", 0))
    cost_pr_labels = json.dumps(list(cost_by_pr.keys()))
    cost_pr_values = json.dumps([round(v, 2) for v in cost_by_pr.values()])

    # Skills usage frequency
    skill_counts = Counter()
    for r in rows:
        skills = r.get("skills_used", "")
        if skills:
            for s in skills.split(","):
                s = s.strip()
                if s:
                    skill_counts[s] += 1
    skill_labels = json.dumps(list(skill_counts.keys()) if skill_counts else ["(none)"])
    skill_values = json.dumps(list(skill_counts.values()) if skill_counts else [1])

    # Model distribution
    model_counts = Counter()
    for r in rows:
        models = r.get("models_used", "")
        if models:
            for m in models.split(","):
                m = m.strip()
                if m:
                    model_counts[m] += 1
    model_labels = json.dumps(list(model_counts.keys()) if model_counts else ["(none)"])
    model_values = json.dumps(list(model_counts.values()) if model_counts else [1])

    # Sessions over time (by date)
    sessions_by_date = Counter()
    for r in rows:
        started = r.get("session_started", "")
        if started:
            date_str = str(started)[:10]  # YYYY-MM-DD
            if date_str and date_str != "None":
                sessions_by_date[date_str] += 1
    sorted_dates = sorted(sessions_by_date.keys())
    date_labels = json.dumps(sorted_dates if sorted_dates else ["(no data)"])
    date_values = json.dumps(
        [sessions_by_date[d] for d in sorted_dates] if sorted_dates else [0]
    )

    # Chart.js color palette
    colors = [
        "'#4CAF50'",
        "'#2196F3'",
        "'#FF9800'",
        "'#9C27B0'",
        "'#F44336'",
        "'#00BCD4'",
        "'#FFC107'",
        "'#795548'",
        "'#607D8B'",
        "'#E91E63'",
        "'#3F51B5'",
        "'#8BC34A'",
    ]

    def color_array(n):
        return "[" + ",".join(colors[i % len(colors)] for i in range(n)) + "]"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code Analytics Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f5; color: #333; padding: 20px; }}
  h1 {{ text-align: center; margin-bottom: 5px; color: #1a1a2e; }}
  .subtitle {{ text-align: center; color: #666; margin-bottom: 20px; font-size: 14px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 20px;
           box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
  .card .value {{ font-size: 32px; font-weight: 700; color: #1a1a2e; }}
  .card .label {{ font-size: 14px; color: #666; margin-top: 4px; }}
  .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
             gap: 20px; }}
  .chart-box {{ background: #fff; border-radius: 8px; padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .chart-box h3 {{ margin-bottom: 12px; color: #1a1a2e; }}
  canvas {{ max-height: 350px; }}
  .footer {{ text-align: center; margin-top: 24px; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<h1>Claude Code Analytics Dashboard</h1>
<p class="subtitle">{repo} &mdash; {from_date} to {to_date}</p>

<div class="cards">
  <div class="card"><div class="value">{total_sessions}</div><div class="label">Sessions</div></div>
  <div class="card"><div class="value">${total_cost:.2f}</div><div class="label">Total Cost</div></div>
  <div class="card"><div class="value">{total_prs_issues}</div><div class="label">PRs / Issues</div></div>
  <div class="card"><div class="value">{total_commits}</div><div class="label">Commits</div></div>
</div>

<div class="charts">
  <div class="chart-box">
    <h3>Cost per PR</h3>
    <canvas id="costChart"></canvas>
  </div>
  <div class="chart-box">
    <h3>Skills Usage</h3>
    <canvas id="skillsChart"></canvas>
  </div>
  <div class="chart-box">
    <h3>Model Distribution</h3>
    <canvas id="modelChart"></canvas>
  </div>
  <div class="chart-box">
    <h3>Sessions Over Time</h3>
    <canvas id="timeChart"></canvas>
  </div>
</div>

<div class="footer">Generated by session-analytics.py &mdash; {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</div>

<script>
// Cost per PR - Bar chart
new Chart(document.getElementById('costChart'), {{
  type: 'bar',
  data: {{
    labels: {cost_pr_labels},
    datasets: [{{ label: 'Cost (USD)', data: {cost_pr_values},
      backgroundColor: {color_array(len(cost_by_pr))},
    }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
}});

// Skills Usage - Pie chart
new Chart(document.getElementById('skillsChart'), {{
  type: 'pie',
  data: {{
    labels: {skill_labels},
    datasets: [{{ data: {skill_values},
      backgroundColor: {color_array(max(len(skill_counts), 1))},
    }}]
  }},
  options: {{ responsive: true }}
}});

// Model Distribution - Doughnut chart
new Chart(document.getElementById('modelChart'), {{
  type: 'doughnut',
  data: {{
    labels: {model_labels},
    datasets: [{{ data: {model_values},
      backgroundColor: {color_array(max(len(model_counts), 1))},
    }}]
  }},
  options: {{ responsive: true }}
}});

// Sessions Over Time - Line chart
new Chart(document.getElementById('timeChart'), {{
  type: 'line',
  data: {{
    labels: {date_labels},
    datasets: [{{ label: 'Sessions', data: {date_values},
      borderColor: '#2196F3', backgroundColor: 'rgba(33,150,243,0.1)',
      fill: true, tension: 0.3,
    }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
}});
</script>
</body>
</html>"""

    with open(path, "w") as f:
        f.write(html)


def phase_extract(args):
    """Extract session data from PR/issue comments to CSV/MD/HTML."""
    if not args.repo:
        print("ERROR: --repo is required for extract phase", file=sys.stderr)
        sys.exit(1)

    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to_date", None)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    # Fetch PRs and issues
    for item_type in ("pr", "issue"):
        print(f"Fetching {item_type}s from {args.repo}...", file=sys.stderr)
        items = _gh_list_items(args.repo, item_type, from_date, to_date)
        print(f"  Found {len(items)} {item_type}(s)", file=sys.stderr)

        for item in items:
            number = item.get("number")
            if not number:
                continue

            comments = _gh_fetch_comments(args.repo, number)

            for comment in comments:
                body = comment.get("body", "")
                # Find session comments with SESSION: marker (not SUMMARY)
                if SESSION_MARKER_PREFIX in body and SUMMARY_MARKER not in body:
                    session_data = parse_session_data_from_comment(body)
                    if session_data:
                        row = _build_extract_row(item, item_type, session_data)
                        rows.append(row)

    print(f"\nExtracted {len(rows)} session(s) total", file=sys.stderr)

    # Write outputs
    csv_path = output_dir / "analytics.csv"
    md_path = output_dir / "analytics.md"
    html_path = output_dir / "dashboard.html"

    write_csv(rows, csv_path)
    print(f"CSV written to:  {csv_path}", file=sys.stderr)

    write_md_report(rows, md_path, args)
    print(f"MD written to:   {md_path}", file=sys.stderr)

    write_html_dashboard(rows, html_path, args)
    print(f"HTML written to: {html_path}", file=sys.stderr)

    return rows


# ---------------------------------------------------------------------------
# Phase: placeholders for future phases
# ---------------------------------------------------------------------------


def phase_placeholder(phase_name, args):
    """Placeholder for phases not yet implemented."""
    print(f"Phase '{phase_name}' is not yet implemented.", file=sys.stderr)
    print(
        "Available phases: stats, mermaid, comment, summary, extract", file=sys.stderr
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def run_self_test():
    """Run basic self-tests to verify the script works correctly."""
    import tempfile

    print("Running self-tests...", file=sys.stderr)
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {name}", file=sys.stderr)
            passed += 1
        else:
            print(f"  FAIL: {name} {detail}", file=sys.stderr)
            failed += 1

    # Test 1: parse_timestamp
    ts = parse_timestamp("2026-01-19T10:06:49.390Z")
    check("parse_timestamp with Z", ts is not None and ts.year == 2026)

    ts2 = parse_timestamp("2026-01-19T10:06:49.390+00:00")
    check("parse_timestamp with +00:00", ts2 is not None and ts2.year == 2026)

    check("parse_timestamp None", parse_timestamp(None) is None)
    check("parse_timestamp empty", parse_timestamp("") is None)

    # Test 2: extract_commit_message
    msg = extract_commit_message('git commit -m "Fix the bug"')
    check("extract_commit_message simple", msg == "Fix the bug", f"got: {msg}")

    msg2 = extract_commit_message(
        "git commit -m \"$(cat <<'EOF'\nAdd feature\n\nDetails\nEOF\n)\""
    )
    check("extract_commit_message heredoc", msg2 == "Add feature", f"got: {msg2}")

    check("extract_commit_message None", extract_commit_message(None) is None)
    check("extract_commit_message no git", extract_commit_message("ls -la") is None)

    # Test 3: parse synthetic JSONL
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "test-1234-5678",
                    "gitBranch": "test-branch",
                    "timestamp": "2026-01-01T10:00:00.000Z",
                    "message": {"role": "user", "content": "hello"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T10:00:05.000Z",
                    "message": {
                        "model": "claude-opus-4-6",
                        "role": "assistant",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 200,
                            "cache_creation_input_tokens": 50,
                            "cache_read_input_tokens": 25,
                        },
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "/tmp/test"},
                            },
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T10:01:00.000Z",
                    "message": {
                        "model": "claude-opus-4-6",
                        "role": "assistant",
                        "usage": {
                            "input_tokens": 150,
                            "output_tokens": 300,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 100,
                        },
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": 'git commit -m "Test commit"'},
                            },
                            {
                                "type": "tool_use",
                                "name": "Skill",
                                "input": {"skill": "tdd:ci"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Task",
                                "input": {
                                    "subagent_type": "Explore",
                                    "description": "Research something",
                                    "prompt": "...",
                                },
                            },
                        ],
                    },
                }
            ),
        ]
        tmp.write("\n".join(lines) + "\n")
        tmp.flush()
        tmp_path = Path(tmp.name)

    try:
        stats = parse_session_jsonl(tmp_path)

        check(
            "session_id extracted",
            stats["session_id"] == "test-1234-5678",
            f"got: {stats['session_id']}",
        )
        check(
            "branch extracted",
            stats["branch"] == "test-branch",
            f"got: {stats['branch']}",
        )
        check(
            "duration computed",
            stats["duration_minutes"] == 1,
            f"got: {stats['duration_minutes']}",
        )

        opus = stats["models"].get("claude-opus-4-6", {})
        check(
            "opus messages",
            opus.get("messages") == 2,
            f"got: {opus.get('messages')}",
        )
        check(
            "opus input_tokens",
            opus.get("input_tokens") == 250,
            f"got: {opus.get('input_tokens')}",
        )
        check(
            "opus output_tokens",
            opus.get("output_tokens") == 500,
            f"got: {opus.get('output_tokens')}",
        )
        check(
            "opus cache_creation_tokens",
            opus.get("cache_creation_tokens") == 50,
            f"got: {opus.get('cache_creation_tokens')}",
        )
        check(
            "opus cache_read_tokens",
            opus.get("cache_read_tokens") == 125,
            f"got: {opus.get('cache_read_tokens')}",
        )

        check(
            "total input",
            stats["total_tokens"]["input"] == 250,
            f"got: {stats['total_tokens']['input']}",
        )
        check(
            "total output",
            stats["total_tokens"]["output"] == 500,
            f"got: {stats['total_tokens']['output']}",
        )

        check(
            "no estimated_cost_usd in stats",
            "estimated_cost_usd" not in stats,
            "estimated_cost_usd should not be in stats output",
        )

        check(
            "Bash count",
            stats["tools"].get("Bash") == 2,
            f"got: {stats['tools'].get('Bash')}",
        )
        check(
            "Read count",
            stats["tools"].get("Read") == 1,
            f"got: {stats['tools'].get('Read')}",
        )
        check(
            "Skill count",
            stats["tools"].get("Skill") == 1,
            f"got: {stats['tools'].get('Skill')}",
        )
        check(
            "Task count",
            stats["tools"].get("Task") == 1,
            f"got: {stats['tools'].get('Task')}",
        )

        check(
            "skills_invoked",
            len(stats["skills_invoked"]) == 1
            and stats["skills_invoked"][0]["skill"] == "tdd:ci",
            f"got: {stats['skills_invoked']}",
        )

        check(
            "subagents launched",
            len(stats["subagents"]) == 1 and stats["subagents"][0]["type"] == "Explore",
            f"got: {stats['subagents']}",
        )

        check(
            "commits found",
            len(stats["commits"]) == 1
            and stats["commits"][0]["message"] == "Test commit",
            f"got: {stats['commits']}",
        )

        check(
            "session_id_short",
            stats["session_id_short"] == "test-123",
            f"got: {stats['session_id_short']}",
        )

        check("problems_faced is list", isinstance(stats["problems_faced"], list))
        check("workflow_edges is dict", isinstance(stats["workflow_edges"], dict))
    finally:
        tmp_path.unlink(missing_ok=True)

    # ---- Mermaid phase tests ----
    print("\n--- Mermaid phase tests ---", file=sys.stderr)

    # Test: extract_mermaid_from_skill
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as skill_tmp:
        skill_tmp.write(
            "---\nname: test\n---\n\n"
            "Some text\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "    A --> B\n"
            "    B -->|fail| C\n"
            "    B -->|pass| D\n"
            "```\n\n"
            "More text\n"
        )
        skill_tmp.flush()
        skill_md_path = skill_tmp.name

    try:
        mermaid_content = extract_mermaid_from_skill(skill_md_path)
        check(
            "extract_mermaid_from_skill finds block",
            mermaid_content is not None,
            f"got None",
        )
        check(
            "extract_mermaid_from_skill content",
            mermaid_content is not None and "flowchart TD" in mermaid_content,
            f"got: {mermaid_content!r}",
        )
        check(
            "extract_mermaid_from_skill has edges",
            mermaid_content is not None and "A --> B" in mermaid_content,
            f"got: {mermaid_content!r}",
        )
    finally:
        os.unlink(skill_md_path)

    check(
        "extract_mermaid_from_skill missing file",
        extract_mermaid_from_skill("/nonexistent/SKILL.md") is None,
    )

    # Test: find_edges
    test_lines = [
        "flowchart TD",
        "    A --> B",
        '    B -->|"fail"| C',
        '    B -->|"pass"| D',
        "    D --> E",
        "    classDef foo fill:#fff",
    ]
    edges = find_edges(test_lines)
    check("find_edges count", len(edges) == 4, f"got: {len(edges)}")
    check(
        "find_edges first src/dst",
        len(edges) >= 1 and edges[0]["src"] == "A" and edges[0]["dst"] == "B",
        f"got: {edges[0] if edges else 'empty'}",
    )
    check(
        "find_edges failure detection",
        len(edges) >= 2 and edges[1]["is_failure"] is True,
        f"got: {edges[1] if len(edges) >= 2 else 'N/A'}",
    )
    check(
        "find_edges success detection",
        len(edges) >= 3 and edges[2]["is_failure"] is False,
        f"got: {edges[2] if len(edges) >= 3 else 'N/A'}",
    )
    check(
        "find_edges skips classDef",
        all(e["src"] != "classDef" for e in edges),
    )

    # Test: annotate_mermaid - basic coloring
    test_template = (
        "flowchart TD\n"
        "    START --> WORK\n"
        '    WORK -->|"error"| FAIL\n'
        '    WORK -->|"ok"| DONE\n'
        "    classDef tdd fill:#4CAF50"
    )
    edge_counts = {"START->WORK": 1, "WORK->DONE": 1}
    used_nodes = {"START", "WORK", "DONE"}

    annotated = annotate_mermaid(test_template, edge_counts, used_nodes)

    check(
        "annotate_mermaid adds green linkStyle",
        f"stroke:{COLOR_GREEN}" in annotated,
        f"green color not found in annotated output",
    )
    check(
        "annotate_mermaid adds grey for untraversed",
        f"stroke:{COLOR_GREY}" in annotated,
        f"grey color not found in annotated output",
    )
    check(
        "annotate_mermaid adds traversal count",
        "(1x)" in annotated,
        f"traversal count not found in annotated output",
    )
    check(
        "annotate_mermaid adds node style",
        NODE_STYLE_USED in annotated,
        f"node style not found in annotated output",
    )

    # Test: annotate_mermaid - failure edge coloring
    fail_edge_counts = {"START->WORK": 1, "WORK->FAIL": 1}
    fail_used_nodes = {"START", "WORK", "FAIL"}
    fail_annotated = annotate_mermaid(test_template, fail_edge_counts, fail_used_nodes)

    check(
        "annotate_mermaid failure edge is red",
        f"stroke:{COLOR_RED}" in fail_annotated,
        f"red color not found in annotated output",
    )

    # Test: annotate_mermaid - edge label with count
    annotated_lines = annotated.split("\n")
    ok_line = [
        l
        for l in annotated_lines
        if "DONE" in l and "ok" in l and not l.strip().startswith("style")
    ]
    check(
        "annotate_mermaid label with count format",
        len(ok_line) == 1 and "ok (1x)" in ok_line[0],
        f"got: {ok_line}",
    )

    # Test: annotate_mermaid - edge without label gets count only
    no_label_line = [l for l in annotated_lines if "START" in l and "WORK" in l]
    check(
        "annotate_mermaid no-label edge gets count",
        len(no_label_line) == 1 and '"1x"' in no_label_line[0],
        f"got: {no_label_line}",
    )

    # Test: find_skill_workflow with temp directory structure
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create skill directory: tmpdir/myskill/SKILL.md
        skill_dir = os.path.join(tmpdir, "myskill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("# Skill\n\n```mermaid\nflowchart TD\n    X --> Y\n```\n")

        # Create colon-notation skill: tmpdir/myskill:sub/SKILL.md
        sub_dir = os.path.join(tmpdir, "myskill:sub")
        os.makedirs(sub_dir)
        with open(os.path.join(sub_dir, "SKILL.md"), "w") as f:
            f.write("# Sub\n\n```mermaid\nflowchart TD\n    P --> Q\n```\n")

        wf = find_skill_workflow("myskill", tmpdir)
        check(
            "find_skill_workflow exact match",
            wf is not None and "X --> Y" in wf,
            f"got: {wf!r}",
        )

        wf_sub = find_skill_workflow("myskill:sub", tmpdir)
        check(
            "find_skill_workflow colon notation exact",
            wf_sub is not None and "P --> Q" in wf_sub,
            f"got: {wf_sub!r}",
        )

        wf_fallback = find_skill_workflow("myskill:other", tmpdir)
        check(
            "find_skill_workflow colon fallback to parent",
            wf_fallback is not None and "X --> Y" in wf_fallback,
            f"got: {wf_fallback!r}",
        )

        wf_missing = find_skill_workflow("nonexistent", tmpdir)
        check(
            "find_skill_workflow missing skill",
            wf_missing is None,
        )

    # Test: phase_mermaid end-to-end with synthetic data
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create skill with mermaid
        skill_dir = os.path.join(tmpdir, "skills", "deploy")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(
                "---\nname: deploy\n---\n\n"
                "```mermaid\n"
                "flowchart TD\n"
                "    BUILD --> TEST\n"
                '    TEST -->|"fail"| FIX\n'
                '    TEST -->|"pass"| DEPLOY\n'
                "    FIX --> BUILD\n"
                "    classDef ok fill:#4CAF50\n"
                "```\n"
            )

        # Create stats JSON with workflow_edges
        stats_data = {
            "session_id": "test-mermaid",
            "session_id_short": "test-mer",
            "skills_invoked": [{"skill": "deploy", "count": 2, "status": "unknown"}],
            "workflow_edges": {
                "deploy": {
                    "BUILD->TEST": 3,
                    "TEST->DEPLOY": 1,
                    "TEST->FIX": 2,
                    "FIX->BUILD": 2,
                }
            },
        }
        stats_file = os.path.join(tmpdir, "test-stats.json")
        with open(stats_file, "w") as f:
            json.dump(stats_data, f)

        # Run phase_mermaid
        test_args = parse_args(
            [
                "--phase",
                "mermaid",
                "--stats-file",
                stats_file,
                "--skills-dir",
                os.path.join(tmpdir, "skills"),
            ]
        )
        diagrams = phase_mermaid(test_args)

        check(
            "phase_mermaid returns diagrams dict",
            isinstance(diagrams, dict),
            f"got: {type(diagrams)}",
        )
        check(
            "phase_mermaid has deploy diagram",
            "deploy" in diagrams,
            f"keys: {list(diagrams.keys())}",
        )

        if "deploy" in diagrams:
            d = diagrams["deploy"]
            check(
                "phase_mermaid deploy has green edges",
                f"stroke:{COLOR_GREEN}" in d,
                "no green edges",
            )
            check(
                "phase_mermaid deploy has red edges",
                f"stroke:{COLOR_RED}" in d,
                "no red edges (fail edge should be red)",
            )
            check(
                "phase_mermaid deploy has traversal counts",
                '"3x"' in d or "(3x)" in d,
                "no 3x traversal count for BUILD->TEST",
            )
            check(
                "phase_mermaid deploy has node styles",
                NODE_STYLE_USED in d,
                "no node styles",
            )

        # Check diagrams.json was written
        diagrams_file = os.path.join(tmpdir, "test-diagrams.json")
        check(
            "phase_mermaid writes diagrams.json",
            os.path.isfile(diagrams_file),
            f"expected: {diagrams_file}",
        )

    # ---- Comment / Summary phase tests ----
    print("\n--- Comment / Summary phase tests ---", file=sys.stderr)

    # Test: format_duration
    check("format_duration 0", format_duration(0) == "0m", f"got: {format_duration(0)}")
    check(
        "format_duration 45",
        format_duration(45) == "45m",
        f"got: {format_duration(45)}",
    )
    check(
        "format_duration 78",
        format_duration(78) == "1h 18m",
        f"got: {format_duration(78)}",
    )
    check(
        "format_duration 120",
        format_duration(120) == "2h 0m",
        f"got: {format_duration(120)}",
    )
    check(
        "format_duration 1",
        format_duration(1) == "1m",
        f"got: {format_duration(1)}",
    )
    check(
        "format_duration 59",
        format_duration(59) == "59m",
        f"got: {format_duration(59)}",
    )
    check(
        "format_duration 60",
        format_duration(60) == "1h 0m",
        f"got: {format_duration(60)}",
    )
    check(
        "format_duration 1440",
        format_duration(1440) == "24h 0m",
        f"got: {format_duration(1440)}",
    )

    # Test: format_tokens
    check("format_tokens 0", format_tokens(0) == "0", f"got: {format_tokens(0)}")
    check(
        "format_tokens 500", format_tokens(500) == "500", f"got: {format_tokens(500)}"
    )
    check(
        "format_tokens 999", format_tokens(999) == "999", f"got: {format_tokens(999)}"
    )
    check(
        "format_tokens 1000",
        format_tokens(1000) == "1.0K",
        f"got: {format_tokens(1000)}",
    )
    check(
        "format_tokens 1500",
        format_tokens(1500) == "1.5K",
        f"got: {format_tokens(1500)}",
    )
    check(
        "format_tokens 25000",
        format_tokens(25000) == "25.0K",
        f"got: {format_tokens(25000)}",
    )
    check(
        "format_tokens 999999",
        format_tokens(999999) == "1000.0K",
        f"got: {format_tokens(999999)}",
    )
    check(
        "format_tokens 1000000",
        format_tokens(1000000) == "1.0M",
        f"got: {format_tokens(1000000)}",
    )
    check(
        "format_tokens 1500000",
        format_tokens(1500000) == "1.5M",
        f"got: {format_tokens(1500000)}",
    )
    check(
        "format_tokens 458575867",
        format_tokens(458575867) == "458.6M",
        f"got: {format_tokens(458575867)}",
    )

    # Test: format_session_comment - verify all sections
    test_stats = {
        "session_id": "00b11888-7e0c-4fb0-abcd-1234567890ab",
        "session_id_short": "00b11888",
        "branch": "feature-test",
        "started_at": "2026-01-01T10:00:00+00:00",
        "ended_at": "2026-01-01T11:18:00+00:00",
        "duration_minutes": 78,
        "models": {
            "claude-opus-4-6": {
                "messages": 100,
                "input_tokens": 50000,
                "output_tokens": 20000,
                "cache_creation_tokens": 10000,
                "cache_read_tokens": 5000,
            }
        },
        "total_tokens": {
            "input": 50000,
            "output": 20000,
            "cache_creation": 10000,
            "cache_read": 5000,
        },
        "estimated_cost_usd": 12.45,
        "tools": {"Bash": 50, "Read": 30, "Edit": 20, "Grep": 10},
        "skills_invoked": [
            {"skill": "tdd:ci", "count": 3, "status": "unknown"},
            {"skill": "rca:ci", "count": 1, "status": "unknown"},
        ],
        "subagents": [
            {
                "id": "task-0",
                "type": "Explore",
                "model": "claude-opus-4-6",
                "tokens": {"total": 46320},
                "tool_uses": 42,
                "duration_ms": 1832865,
                "description": "Research something",
            }
        ],
        "commits": [
            {"message": "Add feature X"},
            {"message": "Fix bug Y"},
        ],
        "problems_faced": ["Build failed on CI", "Flaky test"],
        "workflow_edges": {},
    }

    comment_body = format_session_comment(test_stats)

    check(
        "comment has session marker",
        "<!-- SESSION:00b11888-7e0c-4f" in comment_body,
        f"marker not found",
    )
    check(
        "comment has TL;DR",
        "**TL;DR:**" in comment_body,
        "TL;DR not found",
    )
    check(
        "comment TL;DR has session id",
        "`00b11888`" in comment_body,
        "session id not in TL;DR",
    )
    check(
        "comment TL;DR has model",
        "opus-4-6" in comment_body,
        "model not in TL;DR",
    )
    check(
        "comment TL;DR has duration",
        "1h 18m" in comment_body,
        "duration not in TL;DR",
    )
    check(
        "comment TL;DR no cost",
        "$12.45" not in comment_body,
        "cost should not appear in TL;DR",
    )
    check(
        "comment TL;DR has commits",
        "2 commits" in comment_body,
        "commits not in TL;DR",
    )
    check(
        "comment TL;DR has skills",
        "tdd:ci" in comment_body and "rca:ci" in comment_body,
        "skills not in TL;DR",
    )
    check(
        "comment has header",
        "### Session `00b11888`" in comment_body,
        "header not found",
    )
    check(
        "comment has token usage table",
        "#### Token Usage" in comment_body,
        "token usage section not found",
    )
    check(
        "comment has subagents",
        "#### Subagents" in comment_body,
        "subagents section not found",
    )
    check(
        "comment has skills table",
        "#### Skills" in comment_body,
        "skills section not found",
    )
    check(
        "comment has tool usage",
        "Tool Usage" in comment_body and "<details>" in comment_body,
        "tool usage section not found",
    )
    check(
        "comment has problems",
        "#### Problems Faced" in comment_body,
        "problems section not found",
    )
    check(
        "comment has commits section",
        "#### Commits" in comment_body and "Add feature X" in comment_body,
        "commits section not found",
    )
    check(
        "comment has session data JSON",
        "Session Data (JSON)" in comment_body,
        "session data section not found",
    )
    check(
        "comment has json block",
        "```json" in comment_body,
        "json block not found",
    )

    # Test with diagrams
    test_diagrams = {"deploy": "flowchart TD\n    BUILD --> TEST"}
    comment_with_diagrams = format_session_comment(test_stats, test_diagrams)
    check(
        "comment with diagrams has mermaid",
        "```mermaid" in comment_with_diagrams,
        "mermaid block not found",
    )
    check(
        "comment with diagrams has diagram name",
        "**deploy**" in comment_with_diagrams,
        "diagram name not found",
    )

    # Test: parse_session_data_from_comment - round-trip
    parsed = parse_session_data_from_comment(comment_body)
    check(
        "parse_session_data round-trip not None",
        parsed is not None,
        "parsed is None",
    )
    if parsed:
        check(
            "parse_session_data session_id",
            parsed.get("session_id") == test_stats["session_id"],
            f"got: {parsed.get('session_id')}",
        )
        check(
            "parse_session_data total input",
            parsed.get("total_tokens", {}).get("input")
            == test_stats["total_tokens"]["input"],
            f"got: {parsed.get('total_tokens', {}).get('input')}",
        )
        check(
            "parse_session_data commits count",
            len(parsed.get("commits", [])) == len(test_stats["commits"]),
            f"got: {len(parsed.get('commits', []))}",
        )

    # Test: parse_session_data_from_comment with bad input
    check(
        "parse_session_data bad input",
        parse_session_data_from_comment("no data here") is None,
        "expected None for bad input",
    )
    check(
        "parse_session_data empty",
        parse_session_data_from_comment("") is None,
        "expected None for empty",
    )

    # Test: format_summary_comment
    session1 = {
        "session_id": "sess-aaa",
        "session_id_short": "sess-aaa",
        "branch": "branch-a",
        "duration_minutes": 60,
        "total_tokens": {
            "input": 10000,
            "output": 5000,
            "cache_creation": 2000,
            "cache_read": 1000,
        },
        "estimated_cost_usd": 5.50,
        "commits": [{"message": "commit 1"}],
    }
    session2 = {
        "session_id": "sess-bbb",
        "session_id_short": "sess-bbb",
        "branch": "branch-b",
        "duration_minutes": 30,
        "total_tokens": {
            "input": 8000,
            "output": 3000,
            "cache_creation": 1000,
            "cache_read": 500,
        },
        "estimated_cost_usd": 3.25,
        "commits": [{"message": "commit 2"}, {"message": "commit 3"}],
    }

    summary_body = format_summary_comment([session1, session2])

    check(
        "summary has marker",
        SUMMARY_MARKER in summary_body,
        "summary marker not found",
    )
    check(
        "summary has TL;DR",
        "**TL;DR:**" in summary_body,
        "TL;DR not found",
    )
    check(
        "summary TL;DR has session count",
        "2 sessions" in summary_body,
        "session count not in TL;DR",
    )
    check(
        "summary has aggregate table",
        "#### Aggregate Token Usage" in summary_body,
        "aggregate section not found",
    )
    check(
        "summary has session history",
        "#### Session History" in summary_body,
        "session history not found",
    )
    check(
        "summary has totals verification",
        "#### Totals Verification" in summary_body,
        "totals verification not found",
    )

    # Verify sums match
    check(
        "summary no cost",
        "$5.50" not in summary_body and "$3.25" not in summary_body,
        "cost should not appear in summary",
    )
    check(
        "summary commits sum",
        "**3**" in summary_body,
        "expected 3 total commits in summary",
    )
    check(
        "summary duration sum",
        "1h 30m" in summary_body,
        "expected 1h 30m total duration",
    )
    check(
        "summary input tokens",
        format_tokens(18000) in summary_body,
        f"expected {format_tokens(18000)} input tokens",
    )

    # Test: _session_marker
    marker = _session_marker("00b11888-7e0c-4fb0-abcd-1234567890ab")
    check(
        "session_marker format",
        marker == "<!-- SESSION:00b11888-7e0c-4f -->",
        f"got: {marker}",
    )
    check(
        "session_marker short id",
        _session_marker("abc") == "<!-- SESSION:abc -->",
        f"got: {_session_marker('abc')}",
    )

    # Test: format_session_comment with no optional sections
    minimal_stats = {
        "session_id": "min-test-1234",
        "session_id_short": "min-test",
        "branch": "",
        "duration_minutes": 5,
        "models": {},
        "total_tokens": {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0},
        "estimated_cost_usd": 0.0,
        "tools": {},
        "skills_invoked": [],
        "subagents": [],
        "commits": [],
        "problems_faced": [],
        "workflow_edges": {},
    }
    minimal_comment = format_session_comment(minimal_stats)
    check(
        "minimal comment has marker",
        "<!-- SESSION:min-test-1234" in minimal_comment,
        "marker not found in minimal comment",
    )
    check(
        "minimal comment has TL;DR",
        "**TL;DR:**" in minimal_comment,
        "TL;DR not found in minimal comment",
    )
    check(
        "minimal comment no subagents section",
        "#### Subagents" not in minimal_comment,
        "subagents should not appear when empty",
    )
    check(
        "minimal comment no skills section",
        "#### Skills" not in minimal_comment,
        "skills should not appear when empty",
    )
    check(
        "minimal comment no problems section",
        "#### Problems Faced" not in minimal_comment,
        "problems should not appear when empty",
    )
    check(
        "minimal comment no commits section",
        "#### Commits" not in minimal_comment,
        "commits should not appear when empty",
    )

    # ---- Extract phase tests ----
    print("\n--- Extract phase tests ---", file=sys.stderr)

    # Build synthetic extract rows for testing
    synthetic_rows = [
        {
            "pr_number": 42,
            "target_type": "pr",
            "pr_title": "Add feature X",
            "pr_author": "alice",
            "pr_status": "merged",
            "session_id": "aaa-1111-2222-3333",
            "session_started": "2026-01-10T09:00:00+00:00",
            "session_duration_min": 45,
            "models_used": "claude-opus-4-6",
            "total_input_tokens": 50000,
            "total_output_tokens": 20000,
            "total_cache_create": 8000,
            "total_cache_read": 3000,
            "estimated_cost_usd": 5.25,
            "commits_count": 2,
            "commit_shas": "abc1234;def5678",
            "skills_used": "tdd:ci,k8s:health",
            "per_skill_tokens": '{"tdd:ci":{"in":1000,"out":500}}',
            "subagent_count": 1,
            "per_subagent_tokens": '{"Explore":{"total":3000}}',
            "problems_count": 1,
            "problems_resolved": 0,
            "lines_added": 120,
            "lines_removed": 30,
            "time_to_merge_hours": 4.5,
            "acceptance_status": "merged",
        },
        {
            "pr_number": 43,
            "target_type": "pr",
            "pr_title": "Fix bug Y",
            "pr_author": "bob",
            "pr_status": "open",
            "session_id": "bbb-4444-5555-6666",
            "session_started": "2026-01-12T14:00:00+00:00",
            "session_duration_min": 30,
            "models_used": "claude-sonnet-4-5-20250514",
            "total_input_tokens": 30000,
            "total_output_tokens": 10000,
            "total_cache_create": 5000,
            "total_cache_read": 2000,
            "estimated_cost_usd": 1.80,
            "commits_count": 1,
            "commit_shas": "ghi9012",
            "skills_used": "tdd:ci",
            "per_skill_tokens": '{"tdd:ci":{"in":500,"out":200}}',
            "subagent_count": 0,
            "per_subagent_tokens": "",
            "problems_count": 0,
            "problems_resolved": 0,
            "lines_added": 50,
            "lines_removed": 10,
            "time_to_merge_hours": "",
            "acceptance_status": "open",
        },
        {
            "pr_number": 10,
            "target_type": "issue",
            "pr_title": "Investigate flaky test",
            "pr_author": "carol",
            "pr_status": "closed",
            "session_id": "ccc-7777-8888-9999",
            "session_started": "2026-01-15T08:30:00+00:00",
            "session_duration_min": 20,
            "models_used": "claude-opus-4-6,claude-sonnet-4-5-20250514",
            "total_input_tokens": 15000,
            "total_output_tokens": 5000,
            "total_cache_create": 2000,
            "total_cache_read": 1000,
            "estimated_cost_usd": 0.95,
            "commits_count": 0,
            "commit_shas": "",
            "skills_used": "",
            "per_skill_tokens": "",
            "subagent_count": 0,
            "per_subagent_tokens": "",
            "problems_count": 2,
            "problems_resolved": 0,
            "lines_added": "",
            "lines_removed": "",
            "time_to_merge_hours": "",
            "acceptance_status": "closed",
        },
    ]

    # Test: CSV round-trip
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test_analytics.csv")
        write_csv(synthetic_rows, csv_path)

        check(
            "write_csv creates file",
            os.path.isfile(csv_path),
            f"file not found: {csv_path}",
        )

        # Read CSV back
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)

        check(
            "csv round-trip row count",
            len(csv_rows) == 3,
            f"expected 3 rows, got {len(csv_rows)}",
        )
        check(
            "csv has all columns",
            set(csv_rows[0].keys()) == set(EXTRACT_CSV_COLUMNS),
            f"columns mismatch: got {set(csv_rows[0].keys())} vs expected {set(EXTRACT_CSV_COLUMNS)}",
        )
        check(
            "csv round-trip pr_number",
            csv_rows[0]["pr_number"] == "42",
            f"got: {csv_rows[0]['pr_number']}",
        )
        check(
            "csv round-trip session_id",
            csv_rows[0]["session_id"] == "aaa-1111-2222-3333",
            f"got: {csv_rows[0]['session_id']}",
        )
        check(
            "csv round-trip cost",
            csv_rows[0]["estimated_cost_usd"] == "5.25",
            f"got: {csv_rows[0]['estimated_cost_usd']}",
        )
        check(
            "csv round-trip target_type",
            csv_rows[2]["target_type"] == "issue",
            f"got: {csv_rows[2]['target_type']}",
        )

    # Test: write_md_report
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = os.path.join(tmpdir, "test_analytics.md")
        test_md_args = parse_args(
            [
                "--phase",
                "extract",
                "--repo",
                "test/repo",
                "--from-date",
                "2026-01-01",
                "--to-date",
                "2026-01-31",
            ]
        )
        write_md_report(synthetic_rows, md_path, test_md_args)

        check(
            "write_md_report creates file",
            os.path.isfile(md_path),
            f"file not found: {md_path}",
        )

        with open(md_path, "r") as f:
            md_content = f.read()

        check(
            "md has title",
            "# Claude Code Analytics Report" in md_content,
            "title not found",
        )
        check(
            "md has period",
            "2026-01-01" in md_content and "2026-01-31" in md_content,
            "period not found",
        )
        check(
            "md has repository",
            "test/repo" in md_content,
            "repository not found",
        )
        check(
            "md has summary section",
            "## Summary" in md_content,
            "summary section not found",
        )
        check(
            "md has total sessions",
            "| Total sessions | 3 |" in md_content,
            "total sessions not found",
        )
        total_test_cost = 5.25 + 1.80 + 0.95
        check(
            "md has total cost",
            f"${total_test_cost:.2f}" in md_content,
            f"expected ${total_test_cost:.2f} in md",
        )
        check(
            "md has per-PR breakdown",
            "## Per-PR Breakdown" in md_content,
            "per-PR breakdown not found",
        )
        check(
            "md has model usage",
            "## Model Usage Distribution" in md_content,
            "model usage section not found",
        )
        check(
            "md has opus model",
            "claude-opus-4-6" in md_content,
            "opus model not found in model distribution",
        )
        check(
            "md has sonnet model",
            "claude-sonnet-4-5-20250514" in md_content,
            "sonnet model not found in model distribution",
        )
        check(
            "md has PRs with session data count",
            "| PRs with session data | 2 |" in md_content,
            "PRs count incorrect",
        )
        check(
            "md has issues with session data count",
            "| Issues with session data | 1 |" in md_content,
            "issues count incorrect",
        )

    # Test: write_html_dashboard
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = os.path.join(tmpdir, "test_dashboard.html")
        test_html_args = parse_args(
            [
                "--phase",
                "extract",
                "--repo",
                "test/repo",
                "--from-date",
                "2026-01-01",
                "--to-date",
                "2026-01-31",
            ]
        )
        write_html_dashboard(synthetic_rows, html_path, test_html_args)

        check(
            "write_html_dashboard creates file",
            os.path.isfile(html_path),
            f"file not found: {html_path}",
        )

        with open(html_path, "r") as f:
            html_content = f.read()

        check(
            "html has doctype",
            "<!DOCTYPE html>" in html_content,
            "DOCTYPE not found",
        )
        check(
            "html has chart.js CDN",
            "chart.js" in html_content or "chart.umd.min.js" in html_content,
            "Chart.js CDN not found",
        )
        check(
            "html has title",
            "Claude Code Analytics Dashboard" in html_content,
            "title not found",
        )
        check(
            "html has session count card",
            ">3</div>" in html_content,
            "session count card not found",
        )
        check(
            "html has total cost card",
            f">${total_test_cost:.2f}</div>" in html_content,
            f"total cost card not found (expected ${total_test_cost:.2f})",
        )
        check(
            "html has commits card",
            ">3</div>" in html_content,
            "commits card not found",
        )
        check(
            "html has cost chart canvas",
            'id="costChart"' in html_content,
            "cost chart canvas not found",
        )
        check(
            "html has skills chart canvas",
            'id="skillsChart"' in html_content,
            "skills chart canvas not found",
        )
        check(
            "html has model chart canvas",
            'id="modelChart"' in html_content,
            "model chart canvas not found",
        )
        check(
            "html has time chart canvas",
            'id="timeChart"' in html_content,
            "time chart canvas not found",
        )
        check(
            "html has new Chart calls",
            html_content.count("new Chart") == 4,
            f"expected 4 Chart instances, got {html_content.count('new Chart')}",
        )
        check(
            "html has repo info",
            "test/repo" in html_content,
            "repo not in HTML",
        )

    # Test: _build_extract_row with synthetic data
    test_item = {
        "number": 99,
        "title": "Test PR",
        "author": {"login": "tester"},
        "state": "MERGED",
        "additions": 200,
        "deletions": 50,
        "createdAt": "2026-01-01T10:00:00Z",
        "mergedAt": "2026-01-01T14:00:00Z",
    }
    test_session = {
        "session_id": "build-row-test-id",
        "started_at": "2026-01-01T10:00:00+00:00",
        "duration_minutes": 30,
        "models": {"claude-opus-4-6": {"messages": 5}},
        "total_tokens": {
            "input": 1000,
            "output": 500,
            "cache_creation": 200,
            "cache_read": 100,
        },
        "estimated_cost_usd": 0.50,
        "commits": [
            {"message": "commit A", "sha": "aaaa111"},
            {"message": "commit B", "sha": "bbbb222"},
        ],
        "skills_invoked": [
            {"skill": "k8s:health", "count": 1, "status": "unknown"},
        ],
        "subagents": [
            {
                "type": "Explore",
                "tokens": {"total": 450},
                "tool_uses": 5,
                "duration_ms": 60000,
            },
        ],
        "problems_faced": ["build error"],
    }

    built_row = _build_extract_row(test_item, "pr", test_session)
    check(
        "build_row pr_number",
        built_row["pr_number"] == 99,
        f"got: {built_row['pr_number']}",
    )
    check(
        "build_row target_type",
        built_row["target_type"] == "pr",
        f"got: {built_row['target_type']}",
    )
    check(
        "build_row pr_author",
        built_row["pr_author"] == "tester",
        f"got: {built_row['pr_author']}",
    )
    check(
        "build_row pr_status merged",
        built_row["pr_status"] == "merged",
        f"got: {built_row['pr_status']}",
    )
    check(
        "build_row acceptance_status merged",
        built_row["acceptance_status"] == "merged",
        f"got: {built_row['acceptance_status']}",
    )
    check(
        "build_row time_to_merge_hours",
        built_row["time_to_merge_hours"] == 4.0,
        f"got: {built_row['time_to_merge_hours']}",
    )
    check(
        "build_row lines_added",
        built_row["lines_added"] == 200,
        f"got: {built_row['lines_added']}",
    )
    check(
        "build_row commits_count",
        built_row["commits_count"] == 2,
        f"got: {built_row['commits_count']}",
    )
    check(
        "build_row skills_used",
        built_row["skills_used"] == "k8s:health",
        f"got: {built_row['skills_used']}",
    )
    check(
        "build_row subagent_count",
        built_row["subagent_count"] == 1,
        f"got: {built_row['subagent_count']}",
    )
    check(
        "build_row problems_count",
        built_row["problems_count"] == 1,
        f"got: {built_row['problems_count']}",
    )
    check(
        "build_row models_used",
        built_row["models_used"] == "claude-opus-4-6",
        f"got: {built_row['models_used']}",
    )

    # Test: _compute_pr_status
    check(
        "compute_status pr merged",
        _compute_pr_status({"state": "MERGED"}, "pr") == ("merged", "merged"),
        f"got: {_compute_pr_status({'state': 'MERGED'}, 'pr')}",
    )
    check(
        "compute_status pr closed",
        _compute_pr_status({"state": "CLOSED"}, "pr") == ("closed", "closed"),
        f"got: {_compute_pr_status({'state': 'CLOSED'}, 'pr')}",
    )
    check(
        "compute_status pr open",
        _compute_pr_status({"state": "OPEN"}, "pr") == ("open", "open"),
        f"got: {_compute_pr_status({'state': 'OPEN'}, 'pr')}",
    )
    check(
        "compute_status issue closed",
        _compute_pr_status({"state": "CLOSED"}, "issue") == ("closed", "closed"),
        f"got: {_compute_pr_status({'state': 'CLOSED'}, 'issue')}",
    )

    # Test: _compute_time_to_merge
    check(
        "time_to_merge not pr",
        _compute_time_to_merge({"mergedAt": "x"}, "issue") == "",
        "expected empty for issue",
    )
    check(
        "time_to_merge no merge",
        _compute_time_to_merge({"createdAt": "2026-01-01T10:00:00Z"}, "pr") == "",
        "expected empty when not merged",
    )
    check(
        "time_to_merge calculation",
        _compute_time_to_merge(
            {"createdAt": "2026-01-01T10:00:00Z", "mergedAt": "2026-01-01T16:30:00Z"},
            "pr",
        )
        == 6.5,
        f"got: {_compute_time_to_merge({'createdAt': '2026-01-01T10:00:00Z', 'mergedAt': '2026-01-01T16:30:00Z'}, 'pr')}",
    )

    # Test: write_md_report with empty rows
    with tempfile.TemporaryDirectory() as tmpdir:
        md_empty_path = os.path.join(tmpdir, "empty.md")
        empty_args = parse_args(["--phase", "extract", "--repo", "x/y"])
        write_md_report([], md_empty_path, empty_args)

        with open(md_empty_path, "r") as f:
            empty_md = f.read()

        check(
            "empty md has title",
            "# Claude Code Analytics Report" in empty_md,
            "title not found in empty report",
        )
        check(
            "empty md has zero sessions",
            "| Total sessions | 0 |" in empty_md,
            "zero sessions not found",
        )

    # Test: write_html_dashboard with empty rows
    with tempfile.TemporaryDirectory() as tmpdir:
        html_empty_path = os.path.join(tmpdir, "empty.html")
        write_html_dashboard([], html_empty_path, empty_args)

        with open(html_empty_path, "r") as f:
            empty_html = f.read()

        check(
            "empty html has doctype",
            "<!DOCTYPE html>" in empty_html,
            "DOCTYPE not found in empty dashboard",
        )
        check(
            "empty html has zero sessions",
            ">0</div>" in empty_html,
            "zero sessions card not found",
        )

    # ---- Subagent usage extraction tests ----
    print("\n--- Subagent usage extraction tests ---", file=sys.stderr)

    # Test: format_duration_ms
    check(
        "format_duration_ms 0",
        format_duration_ms(0) == "0s",
        f"got: {format_duration_ms(0)}",
    )
    check(
        "format_duration_ms 45000",
        format_duration_ms(45000) == "45s",
        f"got: {format_duration_ms(45000)}",
    )
    check(
        "format_duration_ms 120000",
        format_duration_ms(120000) == "2m",
        f"got: {format_duration_ms(120000)}",
    )
    check(
        "format_duration_ms 1800000",
        format_duration_ms(1800000) == "30m",
        f"got: {format_duration_ms(1800000)}",
    )
    check(
        "format_duration_ms 3900000",
        format_duration_ms(3900000) == "1h 5m",
        f"got: {format_duration_ms(3900000)}",
    )
    check(
        "format_duration_ms 7200000",
        format_duration_ms(7200000) == "2h",
        f"got: {format_duration_ms(7200000)}",
    )

    # Test: _USAGE_RE regex
    usage_text = (
        "<usage>total_tokens: 46320\ntool_uses: 42\nduration_ms: 1832865</usage>"
    )
    usage_match = _USAGE_RE.search(usage_text)
    check(
        "_USAGE_RE matches usage text",
        usage_match is not None,
        "regex did not match",
    )
    if usage_match:
        check(
            "_USAGE_RE total_tokens",
            usage_match.group(1) == "46320",
            f"got: {usage_match.group(1)}",
        )
        check(
            "_USAGE_RE tool_uses",
            usage_match.group(2) == "42",
            f"got: {usage_match.group(2)}",
        )
        check(
            "_USAGE_RE duration_ms",
            usage_match.group(3) == "1832865",
            f"got: {usage_match.group(3)}",
        )

    # Test: _extract_subagent_usage
    test_subagents = {
        "task-0": {
            "id": "task-0",
            "type": "Explore",
            "model": "",
            "tokens": {"total": 0},
            "tool_uses": 0,
            "duration_ms": 0,
            "description": "Test task",
        }
    }
    test_id_map = {"toolu_abc123": "task-0"}
    _extract_subagent_usage(
        "toolu_abc123",
        "Result text <usage>total_tokens: 22768\ntool_uses: 9\nduration_ms: 37952</usage>",
        test_id_map,
        test_subagents,
    )
    check(
        "extract_subagent_usage total_tokens",
        test_subagents["task-0"]["tokens"]["total"] == 22768,
        f"got: {test_subagents['task-0']['tokens']['total']}",
    )
    check(
        "extract_subagent_usage tool_uses",
        test_subagents["task-0"]["tool_uses"] == 9,
        f"got: {test_subagents['task-0']['tool_uses']}",
    )
    check(
        "extract_subagent_usage duration_ms",
        test_subagents["task-0"]["duration_ms"] == 37952,
        f"got: {test_subagents['task-0']['duration_ms']}",
    )

    # Test: _extract_subagent_usage with unmatched tool_use_id (should not crash)
    _extract_subagent_usage("toolu_unknown", "some text", test_id_map, test_subagents)
    check(
        "extract_subagent_usage unmatched id is no-op",
        test_subagents["task-0"]["tokens"]["total"] == 22768,
        "values changed unexpectedly",
    )

    # Test: _extract_task_notification_usage
    notif_subagents = {
        "task-0": {
            "id": "task-0",
            "type": "Explore",
            "model": "",
            "tokens": {"total": 0},
            "tool_uses": 0,
            "duration_ms": 0,
            "description": "Explore Claude Code session data",
        }
    }
    notification = (
        "<task-notification>\n"
        "<task-id>a6aaab8</task-id>\n"
        "<status>completed</status>\n"
        '<summary>Agent "Explore Claude Code session data" completed</summary>\n'
        "<result>Done</result>\n"
        "<usage>total_tokens: 22768\ntool_uses: 9\nduration_ms: 37952</usage>\n"
        "</task-notification>"
    )
    _extract_task_notification_usage(notification, notif_subagents)
    check(
        "extract_task_notification total_tokens",
        notif_subagents["task-0"]["tokens"]["total"] == 22768,
        f"got: {notif_subagents['task-0']['tokens']['total']}",
    )
    check(
        "extract_task_notification tool_uses",
        notif_subagents["task-0"]["tool_uses"] == 9,
        f"got: {notif_subagents['task-0']['tool_uses']}",
    )
    check(
        "extract_task_notification duration_ms",
        notif_subagents["task-0"]["duration_ms"] == 37952,
        f"got: {notif_subagents['task-0']['duration_ms']}",
    )

    # Test: _extract_task_notification_usage with no match (should not crash)
    _extract_task_notification_usage("no notification here", notif_subagents)
    check(
        "extract_task_notification no-match is no-op",
        notif_subagents["task-0"]["tokens"]["total"] == 22768,
        "values changed unexpectedly",
    )

    # Test: parse synthetic JSONL with Task tool_result containing usage
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "test-usage-1234",
                    "gitBranch": "usage-branch",
                    "timestamp": "2026-01-01T10:00:00.000Z",
                    "message": {"role": "user", "content": "hello"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T10:00:05.000Z",
                    "message": {
                        "model": "claude-opus-4-6",
                        "role": "assistant",
                        "usage": {"input_tokens": 100, "output_tokens": 200},
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_usage_test_1",
                                "name": "Task",
                                "input": {
                                    "subagent_type": "research",
                                    "description": "Analyze session data",
                                    "prompt": "...",
                                },
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T10:01:00.000Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_usage_test_1",
                                "content": "Task completed successfully\n<usage>total_tokens: 15000\ntool_uses: 12\nduration_ms: 90000</usage>",
                            }
                        ],
                    },
                }
            ),
        ]
        tmp.write("\n".join(lines) + "\n")
        tmp.flush()
        tmp_path = Path(tmp.name)

    try:
        usage_stats = parse_session_jsonl(tmp_path)
        usage_sa = usage_stats["subagents"]
        check(
            "usage JSONL: subagent found",
            len(usage_sa) == 1,
            f"got {len(usage_sa)} subagents",
        )
        if usage_sa:
            check(
                "usage JSONL: tokens.total extracted",
                usage_sa[0]["tokens"]["total"] == 15000,
                f"got: {usage_sa[0]['tokens']['total']}",
            )
            check(
                "usage JSONL: tool_uses extracted",
                usage_sa[0]["tool_uses"] == 12,
                f"got: {usage_sa[0]['tool_uses']}",
            )
            check(
                "usage JSONL: duration_ms extracted",
                usage_sa[0]["duration_ms"] == 90000,
                f"got: {usage_sa[0]['duration_ms']}",
            )
            check(
                "usage JSONL: type correct",
                usage_sa[0]["type"] == "research",
                f"got: {usage_sa[0]['type']}",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    # Test: format_session_comment subagents table uses new columns
    sa_comment = format_session_comment(test_stats)
    check(
        "comment subagents table has Total Tokens header",
        "Total Tokens" in sa_comment,
        "Total Tokens column header not found",
    )
    check(
        "comment subagents table has Tool Uses header",
        "Tool Uses" in sa_comment,
        "Tool Uses column header not found",
    )
    check(
        "comment subagents table has Duration header",
        "Duration" in sa_comment and "|----|------|-------|" in sa_comment,
        "Duration column header not found",
    )
    check(
        "comment subagents table no Input/Output headers",
        "| Input |" not in sa_comment
        and "| Output |" not in sa_comment
        or "#### Token Usage" in sa_comment,  # Input/Output only in Token Usage section
        "old Input/Output headers found in subagents table",
    )

    # Summary
    total = passed + failed
    print(f"\nSelf-test: {passed}/{total} passed", file=sys.stderr)
    if failed > 0:
        sys.exit(1)
    return True


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------


def phase_full_pipeline(args):
    """Run all phases in sequence: stats -> mermaid -> comment -> summary."""
    if not args.session_id:
        print("ERROR: --session-id required for full pipeline", file=sys.stderr)
        sys.exit(1)
    if not all([args.target, args.number, args.repo]):
        print(
            "ERROR: --target, --number, --repo required for full pipeline",
            file=sys.stderr,
        )
        sys.exit(1)

    print("=" * 60)
    print("Phase 1/4: Stats")
    print("=" * 60)
    phase_stats(args)

    # Set stats file for subsequent phases if not set
    if not args.stats_file:
        args.stats_file = os.path.join(
            args.output_dir, f"{args.session_id[:8]}-stats.json"
        )

    print()
    print("=" * 60)
    print("Phase 2/4: Mermaid")
    print("=" * 60)
    phase_mermaid(args)

    print()
    print("=" * 60)
    print("Phase 3/4: Comment")
    print("=" * 60)
    phase_comment(args)

    print()
    print("=" * 60)
    print("Phase 4/4: Summary")
    print("=" * 60)
    phase_summary(args)

    print()
    print("=" * 60)
    print("Pipeline complete")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()

    if args.self_test:
        run_self_test()
        return

    if not args.phase:
        # Full pipeline: stats -> mermaid -> comment -> summary
        phase_full_pipeline(args)
        return

    if args.phase == "stats":
        phase_stats(args)
    elif args.phase == "mermaid":
        phase_mermaid(args)
    elif args.phase == "comment":
        phase_comment(args)
    elif args.phase == "summary":
        phase_summary(args)
    elif args.phase == "extract":
        phase_extract(args)
    elif args.phase == "dashboard":
        # Dashboard is generated as part of extract phase
        print("Dashboard is generated via --phase extract (produces CSV + MD + HTML)")
        print(
            "Run: python3 session-analytics.py --phase extract --repo OWNER/NAME --output-dir /tmp/kagenti/session/"
        )
    else:
        print(f"ERROR: unknown phase '{args.phase}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
