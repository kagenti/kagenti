#!/usr/bin/env python3
"""parse-test-matrix.py — Extract per-agent test matrix from OpenShell E2E logs.

Usage:
    # From a local log file:
    ./parse-test-matrix.sh /tmp/kagenti/tdd-iter8/kind-fulltest.log

    # From a CI run (auto-detects issue_comment Kind run):
    ./parse-test-matrix.sh --ci-kind
    ./parse-test-matrix.sh --ci-hcp
    ./parse-test-matrix.sh --ci-run <run-id>

    # Compare all environments side by side:
    ./parse-test-matrix.sh --all
"""
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ── Agent classification ──
# Maps substrings in test names to agent display labels.
# Tests use either fixture IDs (adk_supervised) or K8s names (adk-agent-supervised)
# in bracket parametrization. Each agent needs patterns matching both forms.
# Order matters — first match wins.
AGENTS = [
    {"id": "claude_sdk",       "display": "Claude SDK"},
    {"id": "adk",              "display": "ADK",               "match": ["adk_supervised", "adk_agent"]},
    {"id": "weather",          "display": "Weather",           "match": ["weather_supervised", "weather_agent"]},
    {"id": "openshell_claude", "display": "Claude Code"},
    {"id": "openshell_opencode","display": "OpenCode"},
    {"id": "openshell_generic","display": "Generic Sandbox"},
    {"id": "nemoclaw_hermes",  "display": "NemoClaw Hermes"},
    {"id": "nemoclaw_openclaw","display": "NemoClaw OpenClaw"},
]

# Normalize hyphens → underscores before matching, so "claude-sdk-agent"
# and "claude_sdk_agent" both match the "claude_sdk" pattern.
AGENT_RULES = [(a["display"], a.get("match", [a["id"]])) for a in AGENTS]
AGENT_ORDER = [a["display"] for a in AGENTS]


# ── Capability definitions ──
#
# Each capability has:
#   id:      canonical lowercase name (test function prefix)
#   display: human-readable label with tier prefix (shown in matrix)
#
# Parser matches test_{id}__ in the test function name.

CAPABILITIES = [
    # Tier 1: Agent Infrastructure (no LLM required)
    {"id": "connectivity",       "display": "T1.1 Connectivity"},
    {"id": "credentials",        "display": "T1.2 Credentials"},
    {"id": "sandbox_lifecycle",   "display": "T1.3 Sandbox lifecycle"},
    {"id": "workspace",           "display": "T1.4 Workspace"},
    {"id": "resource_limits",     "display": "T1.5 Resource limits"},
    # Tier 2: Agent Capabilities (requires LLM)
    {"id": "multiturn",           "display": "T2.1 Multiturn"},
    {"id": "context_isolation",   "display": "T2.2 Context isolation"},
    {"id": "session_resume",      "display": "T2.3 Session resume"},
    {"id": "cross_session_mem",   "display": "T2.4 Cross-session mem"},
    {"id": "streaming",           "display": "T2.5 Streaming"},
    {"id": "tool_calling",        "display": "T2.6 Tool calling"},
    {"id": "mcp_direct",          "display": "T2.7 MCP direct"},
    {"id": "mcp_gateway",         "display": "T2.8 MCP via gateway"},
    {"id": "mcp_discovery",       "display": "T2.9 MCP discovery"},
    {"id": "concurrent_sessions", "display": "T2.10 Concurrent sess"},
    # Tier 3: Skill Execution (per-model parametrized)
    {"id": "skill_pr_review",     "display": "T3.1 Skill: PR review"},
    {"id": "skill_rca",           "display": "T3.2 Skill: RCA"},
    {"id": "skill_security",      "display": "T3.3 Skill: Security"},
    {"id": "skill_github_pr",     "display": "T3.4 Skill: GitHub PR"},
    # Tier 4: Security & Policy
    {"id": "hitl_network",        "display": "T4.1 HITL: Network"},
    {"id": "hitl_tool_approval",  "display": "T4.2 HITL: Tool approv"},
    {"id": "hitl_mcp_approval",   "display": "T4.3 HITL: MCP approv"},
    {"id": "audit_logging",       "display": "T4.4 Audit logging"},
]

CAPABILITY_ORDER = [c["display"] for c in CAPABILITIES]
# Each capability matches test_{id}__ in the test function name
CAPABILITY_RULES = [(c["display"], [f"{c['id']}__"]) for c in CAPABILITIES]

PRIORITY_AGENTS = ["Claude Code", "OpenCode", "NemoClaw OpenClaw", "Claude SDK", "ADK"]


def _normalize(s: str) -> str:
    """Normalize hyphens to underscores for consistent matching."""
    return s.replace("-", "_")


def classify(test_name: str) -> str:
    name = _normalize(test_name)
    for agent, patterns in AGENT_RULES:
        if any(p in name for p in patterns):
            return agent
    return "Infra"


def classify_capability(test_name: str) -> str:
    name = _normalize(test_name)
    for cap, patterns in CAPABILITY_RULES:
        if any(p in name for p in patterns):
            return cap
    return "Other"


def extract_results(source: str) -> list[tuple[str, str]]:
    """Extract (test_name, STATUS) from log text."""
    results = []
    for line in source.splitlines():
        if "test_" not in line:
            continue
        m = re.search(r"(test_\S+)\s+(PASSED|FAILED|SKIPPED|XFAIL|xfail)", line)
        if m:
            results.append((m.group(1), m.group(2).upper()))
    # Deduplicate (same test name + status)
    return sorted(set(results))


def build_matrix(results: list[tuple[str, str]]) -> dict:
    """Build {agent: {PASSED: N, FAILED: N, SKIPPED: N, XFAIL: N, total: N}}."""
    matrix = defaultdict(lambda: defaultdict(int))
    for test_name, status in results:
        agent = classify(test_name)
        matrix[agent][status] += 1
        matrix[agent]["total"] += 1
    return matrix


def print_matrix(matrix: dict, label: str = ""):
    if label:
        print(f"\n### {label}")

    agents_present = [a for a in AGENT_ORDER if a in matrix]
    infra = {k: v for k, v in matrix.items() if k not in AGENT_ORDER}

    total = {"PASSED": 0, "FAILED": 0, "SKIPPED": 0, "XFAIL": 0, "total": 0}

    print(f"\n| {'Agent':<22} | {'Pass':>4} | {'Fail':>4} | {'Skip':>4} | {'xfai':>4} | {'Total':>5} |")
    print(f"|{'-'*24}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*7}|")

    for agent in agents_present:
        d = matrix[agent]
        p, f, s, x, t = d["PASSED"], d["FAILED"], d["SKIPPED"], d["XFAIL"], d["total"]
        print(f"| {agent:<22} | {p:>4} | {f:>4} | {s:>4} | {x:>4} | {t:>5} |")
        for k in total:
            total[k] += d.get(k, 0)

    print(f"|{'-'*24}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*7}|")

    for agent, d in sorted(infra.items()):
        p, f, s, x, t = d["PASSED"], d["FAILED"], d["SKIPPED"], d["XFAIL"], d["total"]
        print(f"| {agent:<22} | {p:>4} | {f:>4} | {s:>4} | {x:>4} | {t:>5} |")
        for k in total:
            total[k] += d.get(k, 0)

    print(f"|{'-'*24}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*6}|{'-'*7}|")
    print(f"| {'**TOTAL**':<22} | {total['PASSED']:>4} | {total['FAILED']:>4} | {total['SKIPPED']:>4} | {total['XFAIL']:>4} | {total['total']:>5} |")


def build_capability_matrix(results: list[tuple[str, str]]) -> dict:
    """Build {capability: {agent: STATUS}} where STATUS is PASS/FAIL/SKIP/MISS."""
    matrix = defaultdict(dict)
    for test_name, status in results:
        agent = classify(test_name)
        if agent == "Infra":
            continue
        cap = classify_capability(test_name)
        if cap == "Other":
            continue
        current = matrix[cap].get(agent, "")
        if status == "FAILED":
            matrix[cap][agent] = "FAIL"
        elif status in ("PASSED", "XFAIL") and current != "FAIL":
            matrix[cap][agent] = "PASS"
        elif status == "SKIPPED" and current not in ("PASS", "FAIL"):
            matrix[cap][agent] = "SKIP"
    return matrix


def print_capability_matrix(results: list[tuple[str, str]], label: str = ""):
    """Print Capability × Agent matrix."""
    if label:
        print(f"\n### {label} — Capability × Agent")

    matrix = build_capability_matrix(results)
    agents_seen = set()
    for cap_agents in matrix.values():
        agents_seen.update(cap_agents.keys())
    agents = [a for a in PRIORITY_AGENTS if a in agents_seen]
    agents += [a for a in AGENT_ORDER if a in agents_seen and a not in agents]

    hdr = f"| {'Capability':<20} |"
    sep = f"|{'-'*22}|"
    for a in agents:
        short = a[:10]
        hdr += f" {short:^10} |"
        sep += f"{'-'*12}|"

    print(f"\n{hdr}")
    print(sep)

    for cap in CAPABILITY_ORDER:
        if cap not in matrix:
            row = f"| {cap:<20} |"
            for a in agents:
                row += f" {'—':^10} |"
            print(row)
            continue
        row = f"| {cap:<20} |"
        for a in agents:
            status = matrix[cap].get(a, "MISS")
            row += f" {status:^10} |"
        print(row)

    # Summary row: count of PASS/FAIL/SKIP/MISS per agent
    print(sep)
    row = f"| {'Coverage':<20} |"
    for a in agents:
        caps_present = sum(1 for cap in CAPABILITY_ORDER if cap in matrix and a in matrix[cap])
        caps_pass = sum(1 for cap in CAPABILITY_ORDER if cap in matrix and matrix[cap].get(a) == "PASS")
        row += f" {caps_pass:>2}/{len(CAPABILITY_ORDER):<6} |"
    print(row)


# ── Per-model metrics ──


def load_metrics(metrics_path: str | None = None) -> list[dict]:
    """Load LLM metrics from JSONL file."""
    if metrics_path and Path(metrics_path).exists():
        lines = Path(metrics_path).read_text().strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    # Auto-detect from LOG_DIR or common locations
    for candidate in [
        os.getenv("LOG_DIR", ""),
        "/tmp/kagenti/tdd-iter8",
        "/tmp/kagenti/tdd-iter7",
    ]:
        path = Path(candidate) / "llm-metrics.json"
        if path.exists():
            lines = path.read_text().strip().splitlines()
            return [json.loads(line) for line in lines if line.strip()]
    return []


def print_model_stats_table(metrics: list[dict], label: str = ""):
    """Print per-model performance stats table."""
    if not metrics:
        return

    if label:
        print(f"\n### {label} — Per-Model Performance")

    # Aggregate by model
    model_stats: dict[str, dict] = defaultdict(lambda: {
        "tests": 0, "pass": 0, "fail": 0,
        "tokens_in": [], "tokens_out": [], "durations": [], "response_lengths": [],
    })
    for m in metrics:
        model = m.get("model", "unknown")
        s = model_stats[model]
        s["tests"] += 1
        if m.get("status") == "PASSED":
            s["pass"] += 1
        else:
            s["fail"] += 1
        s["tokens_in"].append(m.get("tokens_in", 0))
        s["tokens_out"].append(m.get("tokens_out", 0))
        s["durations"].append(m.get("duration_s", 0))
        s["response_lengths"].append(m.get("response_length", 0))

    def _avg(lst):
        return sum(lst) / len(lst) if lst else 0

    print(f"\n| {'Model':<20} | Tests | Pass | Fail | Avg Tok In | Avg Tok Out | Avg Time | Avg Resp Len |")
    print(f"|{'-'*22}|:-----:|:----:|:----:|:----------:|:-----------:|:--------:|:------------:|")
    for model in sorted(model_stats.keys()):
        s = model_stats[model]
        print(
            f"| {model:<20} | {s['tests']:>5} | {s['pass']:>4} | {s['fail']:>4} "
            f"| {_avg(s['tokens_in']):>10.0f} | {_avg(s['tokens_out']):>11.0f} "
            f"| {_avg(s['durations']):>6.1f}s | {_avg(s['response_lengths']):>12.0f} |"
        )

    # Per-model × capability breakdown
    cap_model: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    for m in metrics:
        model = m.get("model", "unknown")
        cap = m.get("capability", "unknown")
        cap_model[cap][model] = {
            "status": m.get("status", "?"),
            "tokens_in": m.get("tokens_in", 0),
            "tokens_out": m.get("tokens_out", 0),
            "duration_s": m.get("duration_s", 0),
        }

    models = sorted(model_stats.keys())
    if len(models) < 2:
        return

    hdr = f"\n| {'Capability':<20} |"
    sep = f"|{'-'*22}|"
    for model in models:
        short = model[:20]
        hdr += f" {short:<22} |"
        sep += f"{'-'*24}|"
    print(hdr)
    print(sep)

    for cap in sorted(cap_model.keys()):
        row = f"| {cap:<20} |"
        for model in models:
            d = cap_model[cap].get(model, {})
            if not d:
                row += f" {'—':<22} |"
            else:
                cell = f"{d['status']} {d['tokens_in']}/{d['tokens_out']} {d['duration_s']:.1f}s"
                row += f" {cell:<22} |"
        print(row)


def gh_run_log(run_id: str) -> str:
    """Fetch CI run log via gh CLI."""
    result = subprocess.run(
        ["gh", "run", "view", str(run_id), "--log"],
        capture_output=True, text=True, timeout=120,
    )
    return result.stdout


def find_ci_kind_run() -> str | None:
    """Find the latest successful issue_comment CI Kind run.

    IMPORTANT: e2e-openshell-kind.yaml fires on BOTH pull_request and
    issue_comment. The pull_request run has NO secrets (fork PR), so LLM
    tests skip. Always use the issue_comment run for full agent coverage.
    """
    result = subprocess.run(
        ["gh", "run", "list", "--workflow", "e2e-openshell-kind.yaml",
         "--limit", "15", "--json", "event,conclusion,databaseId",
         "-q", '[.[] | select(.event=="issue_comment" and .conclusion=="success")][0].databaseId'],
        capture_output=True, text=True, timeout=30,
    )
    run_id = result.stdout.strip()
    if run_id and run_id != "null":
        print(f"CI Kind (issue_comment) run: {run_id}", file=sys.stderr)
        return run_id
    return None


def find_ci_hcp_run() -> str | None:
    """Find the latest successful CI HyperShift run."""
    result = subprocess.run(
        ["gh", "run", "list", "--workflow", "e2e-openshell-hypershift.yaml",
         "--limit", "10", "--json", "event,conclusion,databaseId",
         "-q", '[.[] | select(.conclusion=="success")][0].databaseId'],
        capture_output=True, text=True, timeout=30,
    )
    run_id = result.stdout.strip()
    if run_id and run_id != "null":
        print(f"CI HCP run: {run_id}", file=sys.stderr)
        return run_id
    return None


def process_ci_run(run_id: str, label: str):
    cache = Path(f"/tmp/kagenti/test-matrix-ci-{run_id}.txt")
    if cache.exists():
        log_text = cache.read_text()
    else:
        log_text = gh_run_log(run_id)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(log_text)
    results = extract_results(log_text)
    matrix = build_matrix(results)
    print_matrix(matrix, label)
    print_capability_matrix(results, label)


def process_log_file(path: str, label: str = "", metrics_path: str | None = None):
    text = Path(path).read_text()
    results = extract_results(text)
    if not results:
        print(f"\n### {label or path}: no test results found (deploy may have failed)")
        return
    matrix = build_matrix(results)
    print_matrix(matrix, label or Path(path).name)
    print_capability_matrix(results, label or Path(path).name)

    # Auto-detect metrics file alongside the log
    if not metrics_path:
        metrics_path = str(Path(path).parent / "llm-metrics.json")
    metrics = load_metrics(metrics_path)
    if metrics:
        print_model_stats_table(metrics, label or Path(path).name)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--help", "-h"):
        print(__doc__)
        return

    os.makedirs("/tmp/kagenti", exist_ok=True)

    if args[0] == "--ci-kind":
        run_id = find_ci_kind_run()
        if not run_id:
            print("ERROR: No successful issue_comment CI Kind run found", file=sys.stderr)
            sys.exit(1)
        process_ci_run(run_id, "CI Kind (issue_comment — with secrets)")

    elif args[0] == "--ci-hcp":
        run_id = find_ci_hcp_run()
        if not run_id:
            print("ERROR: No successful CI HCP run found", file=sys.stderr)
            sys.exit(1)
        process_ci_run(run_id, "CI HyperShift")

    elif args[0] == "--metrics":
        metrics = load_metrics(args[1] if len(args) > 1 else None)
        if metrics:
            print_model_stats_table(metrics, "LLM Metrics")
        else:
            print("No metrics found")

    elif args[0] == "--ci-run":
        run_id = args[1]
        process_ci_run(run_id, f"CI Run {run_id}")

    elif args[0] == "--all":
        print("# OpenShell E2E Test Matrix")
        from datetime import datetime, timezone
        print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")

        run_id = find_ci_kind_run()
        if run_id:
            process_ci_run(run_id, "CI Kind (issue_comment — with secrets)")

        run_id = find_ci_hcp_run()
        if run_id:
            process_ci_run(run_id, "CI HyperShift")

        import glob
        for logfile in sorted(glob.glob("/tmp/kagenti/tdd-iter*/kind-fulltest*.log")):
            process_log_file(logfile, f"Local Kind ({Path(logfile).parent.name})")
        for logfile in sorted(glob.glob("/tmp/kagenti/tdd-iter*/hcp-fulltest*.log")):
            process_log_file(logfile, f"Custom HCP ({Path(logfile).parent.name})")

    else:
        process_log_file(args[0])


if __name__ == "__main__":
    main()
