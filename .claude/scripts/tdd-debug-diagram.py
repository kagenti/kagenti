#!/usr/bin/env python3
"""Annotate mermaid diagrams with current-node highlighting, edge coloring, and traversal counts.

Edges are colored by status:
  - Green (#4CAF50): traversed successfully
  - Red (#F44336): traversed on a failure path
  - Orange (#FF9800): not yet traversed

Output is organized per worktree/branch under /tmp/kagenti/tdd/<worktree>/<branch>/

Usage:
    python3 .claude/scripts/tdd-debug-diagram.py \\
        --template .claude/skills/tdd/tdd-workflow.mmd \\
        --current-node TDDCI \\
        --edge-counts '{"TDDCI->HS": 2, "HS->REVIEWS": 1}' \\
        --worktree fix-652 --branch fix/keycloak-652 \\
        [--render-png]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


HIGHLIGHT_STYLE = "fill:#FFEB3B,stroke:#F57F17,stroke-width:4px"
BASE_DIR = "/tmp/kagenti/tdd"

# Keywords in edge labels that indicate failure paths
FAILURE_KEYWORDS = re.compile(
    r"fail|error|stuck|reject|crash|timeout|broken|"
    r"changes needed|issues|no\b|can.t|cannot|inconclusive|"
    r"3\+\s*failures",
    re.IGNORECASE,
)

# Edge colors
COLOR_SUCCESS = "#4CAF50"  # green - traversed OK
COLOR_FAILURE = "#F44336"  # red - traversed failure path
COLOR_PENDING = "#FF9800"  # orange - not yet traversed


def parse_args():
    p = argparse.ArgumentParser(description="Annotate mermaid workflow diagrams")
    p.add_argument("--template", required=True, help="Path to base .mmd template")
    p.add_argument("--current-node", required=True, help="Node ID to highlight")
    p.add_argument("--edge-counts", default="{}", help='JSON: {"SRC->DST": N, ...}')
    p.add_argument("--worktree", default="main", help="Worktree name (default: main)")
    p.add_argument("--branch", default="", help="Branch name (default: auto-detect)")
    p.add_argument("--render-png", action="store_true", help="Render PNG via mmdc")
    return p.parse_args()


def get_output_dir(worktree, branch):
    """Build output dir: /tmp/kagenti/tdd/<worktree>/<branch>/"""
    # Sanitize branch name for filesystem (replace / with _)
    safe_branch = branch.replace("/", "_") if branch else "default"
    return os.path.join(BASE_DIR, worktree, safe_branch)


def detect_branch():
    """Auto-detect current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def find_edges(lines):
    """Find all edge lines and return their indices and parsed info.

    Returns list of dicts: {index, src, dst, label, is_failure}
    """
    edges = []
    edge_pattern = re.compile(
        r"(\b[A-Z][A-Z0-9_]*\b)\s*(--[->.]*)(\|([^|]*)\|)?\s*(\b[A-Z][A-Z0-9_]*\b)"
    )
    for i, line in enumerate(lines):
        # Skip classDef and style lines
        stripped = line.strip()
        if stripped.startswith(("classDef", "style", "%%")):
            continue
        m = edge_pattern.search(line)
        if m:
            label = m.group(4) or ""
            label_clean = label.strip().strip('"')
            is_failure = bool(FAILURE_KEYWORDS.search(label_clean))
            edges.append(
                {
                    "index": len(edges),  # mermaid linkStyle uses declaration order
                    "line": i,
                    "src": m.group(1),
                    "dst": m.group(5),
                    "label": label_clean,
                    "is_failure": is_failure,
                }
            )
    return edges


def highlight_node(lines, node_id):
    """Add a style directive to highlight the current node."""
    style_line = f"    style {node_id} {HIGHLIGHT_STYLE}"
    insert_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith("classDef"):
            insert_idx = i
            break
    lines.insert(insert_idx, style_line)
    return lines


def update_edge_labels(lines, edge_counts):
    """Add traversal counts to edge labels."""
    for edge_key, count in edge_counts.items():
        if count <= 0:
            continue
        parts = edge_key.split("->")
        if len(parts) != 2:
            print(
                f"WARNING: invalid edge key '{edge_key}', expected 'SRC->DST'",
                file=sys.stderr,
            )
            continue
        src, dst = parts[0].strip(), parts[1].strip()

        found = False
        for i, line in enumerate(lines):
            pattern = rf"(\b{re.escape(src)}\b\s*)(--[->.]*)(\|[^|]*\|)?(\s*{re.escape(dst)}\b)"
            m = re.search(pattern, line)
            if m:
                prefix = m.group(1)
                arrow = m.group(2)
                old_label = m.group(3)
                suffix_start = m.start(4)

                count_str = f"{count}x"
                if old_label:
                    inner = old_label.strip("|").strip().strip('"')
                    new_label = f'|"{inner} ({count_str})"|'
                else:
                    new_label = f'|"{count_str}"|'

                new_line = (
                    line[: m.start()] + prefix + arrow + new_label + line[suffix_start:]
                )
                lines[i] = new_line
                found = True
                break

        if not found:
            print(f"WARNING: edge '{edge_key}' not found in template", file=sys.stderr)

    return lines


def color_edges(lines, edges, edge_counts):
    """Add linkStyle directives to color edges green/red/orange."""
    traversed = set()
    for edge_key in edge_counts:
        if edge_counts[edge_key] > 0:
            parts = edge_key.split("->")
            if len(parts) == 2:
                traversed.add((parts[0].strip(), parts[1].strip()))

    link_styles = []
    for edge in edges:
        key = (edge["src"], edge["dst"])
        if key in traversed:
            color = COLOR_FAILURE if edge["is_failure"] else COLOR_SUCCESS
        else:
            color = COLOR_PENDING

        link_styles.append(
            f"    linkStyle {edge['index']} stroke:{color},stroke-width:2px"
        )

    # Insert before classDef lines
    insert_idx = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith(("classDef", "style ")):
            insert_idx = i
            break
    for j, style in enumerate(link_styles):
        lines.insert(insert_idx + j, style)

    return lines


def update_state(node_id, edge_counts, output_path, output_dir):
    """Read/update the debug state file."""
    state_file = os.path.join(output_dir, "tdd-debug-state.json")
    state = {"current_node": "", "edge_counts": {}, "history": []}
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    state["current_node"] = node_id
    state["edge_counts"] = edge_counts
    state["timestamp"] = now
    state["diagram_path"] = output_path
    state["history"].append({"node": node_id, "timestamp": now})

    os.makedirs(output_dir, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    return state, state_file


def render_png(mmd_path):
    """Render .mmd to .png via mmdc if available."""
    if not shutil.which("mmdc"):
        print(
            "mmdc not found, skipping PNG render. Install: npm i -g @mermaid-js/mermaid-cli",
            file=sys.stderr,
        )
        return None
    png_path = mmd_path.rsplit(".", 1)[0] + ".png"
    result = subprocess.run(
        ["mmdc", "-i", mmd_path, "-o", png_path, "--quiet"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return png_path
    print(f"mmdc failed: {result.stderr}", file=sys.stderr)
    return None


def main():
    args = parse_args()

    # Read template
    if not os.path.exists(args.template):
        print(f"ERROR: template not found: {args.template}", file=sys.stderr)
        sys.exit(1)

    with open(args.template) as f:
        lines = f.read().splitlines()

    # Parse edge counts
    try:
        edge_counts = json.loads(args.edge_counts)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid --edge-counts JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Auto-detect branch if not provided
    branch = args.branch or detect_branch()

    # Build output path
    output_dir = get_output_dir(args.worktree, branch)
    output_path = os.path.join(output_dir, "debug-diagram.mmd")

    # Verify node exists in template
    node_found = any(
        re.search(rf"\b{re.escape(args.current_node)}\b", line) for line in lines
    )
    if not node_found:
        print(
            f"WARNING: node '{args.current_node}' not found in template",
            file=sys.stderr,
        )

    # Find all edges for coloring
    edges = find_edges(lines)

    # Apply modifications (order matters: labels first, then colors, then node highlight)
    lines = update_edge_labels(lines, edge_counts)
    lines = color_edges(lines, edges, edge_counts)
    lines = highlight_node(lines, args.current_node)

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Diagram: {output_path}")

    # Update state
    state, state_file = update_state(
        args.current_node, edge_counts, os.path.abspath(output_path), output_dir
    )
    print(f"State:   {state_file}")
    print(f"Current: {args.current_node} | History: {len(state['history'])} steps")
    print(
        f"Edges:   {len(edges)} total, "
        f"{sum(1 for e in edges if (e['src'], e['dst']) in {(k.split('->')[0].strip(), k.split('->')[1].strip()) for k in edge_counts if edge_counts[k] > 0 and '->' in k})} traversed"
    )

    # Optional PNG render
    if args.render_png:
        png = render_png(output_path)
        if png:
            print(f"PNG:     {png}")


if __name__ == "__main__":
    main()
