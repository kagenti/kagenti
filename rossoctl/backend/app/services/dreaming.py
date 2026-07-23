# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Skill "dreaming" service.

A dream run feeds an agent's NEW execution trajectories to a RunSpace
optimization session hosted by the skillberry-store's ask-runspace plugin, which
improves the skills the agent used and writes them back into the store in place.
The store's skill auto-sync then propagates the improved skills to the agent's
namespaces.

Trajectories are read from **Phoenix** — rossoctl's OpenTelemetry trace store,
where agent execution (LLM calls, tool calls) already lands. No new datastore is
introduced: dreaming only *reads* Phoenix (per-agent project) and remembers a
per-agent watermark in a ConfigMap (see dream_state) so it never re-processes a
trajectory it already dreamed on.

Rossoctl already knows where the store lives (skill auto-sync ConfigMap
``registry-url``) and where Phoenix lives (the ``phoenix`` service). The pure
helpers (span parsing, digest, request/MCP composition) are separated from I/O so
they can be unit-tested without a cluster.
"""

import datetime as _dt
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services import dream_state

logger = logging.getLogger(__name__)

# ask-runspace plugin endpoint (relative to the store base URL).
_RUN_PATH = "/plugins/ask-runspace/run"
# Store control-plane MCP mount (SSE), pre-wired so the RunSpace agent can
# create/update skills in the store.
_CONTROL_SSE_PATH = "/control_sse"
# Phoenix GraphQL endpoint.
_PHOENIX_GRAPHQL = "/graphql"

# Hard ceiling on the inlined digest so a run request never grows unbounded.
_DIGEST_CHAR_CAP = 60_000

# A RunSpace job id is an opaque token; constrain it before interpolating into a
# URL path so a caller-supplied value can't steer the request (SSRF / traversal).
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


# ---------------------------------------------------------------------------
# Trajectory selection (Phoenix)
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> Optional[_dt.datetime]:
    """Parse a Phoenix ISO timestamp (handles trailing 'Z')."""
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_SPANS_QUERY = """
query($limit: Int!) {
  projects(first: 100) {
    edges { node {
      name
      spans(first: $limit, sort: {col: startTime, dir: desc}) {
        edges { node { name spanKind startTime attributes context { traceId } } }
      }
    } }
  }
}
"""


async def fetch_new_spans(
    phoenix_url: str,
    project: str,
    since_ts: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Return the agent's NEW Phoenix spans (oldest first).

    Queries the Phoenix project named *project* (rossoctl traces per agent) and
    keeps spans whose startTime is later than *since_ts* (the watermark);
    ``since_ts=None`` (never dreamed) keeps everything up to *limit*. Each result
    carries a parsed ``start_dt`` so the caller can advance the watermark.
    """
    url = phoenix_url.rstrip("/") + _PHOENIX_GRAPHQL
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json={"query": _SPANS_QUERY, "variables": {"limit": limit}})
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}

    since_dt = _parse_ts(since_ts) if since_ts else None
    spans: List[Dict[str, Any]] = []
    for proj_edge in data.get("projects", {}).get("edges", []):
        node = proj_edge.get("node", {})
        if node.get("name") != project:
            continue
        for span_edge in node.get("spans", {}).get("edges", []):
            s = span_edge.get("node", {})
            start_dt = _parse_ts(s.get("startTime"))
            if since_dt and start_dt and start_dt <= since_dt:
                continue
            spans.append(
                {
                    "name": s.get("name"),
                    "span_kind": s.get("spanKind"),
                    "start_time": s.get("startTime"),
                    "start_dt": start_dt,
                    "attributes": s.get("attributes"),
                    "trace_id": (s.get("context") or {}).get("traceId"),
                }
            )
    spans.sort(key=lambda x: x.get("start_time") or "")
    return spans[:limit]


# ---------------------------------------------------------------------------
# Pure composition helpers (unit-tested)
# ---------------------------------------------------------------------------


# Span kinds that carry the agent's actual behavior (vs. framework plumbing).
# A single turn emits many low-level "unknown" a2a spans (event queue, etc.) that
# are noise for optimization, so the digest keeps only the meaningful ones.
_MEANINGFUL_KINDS = {"llm", "tool", "agent", "chain", "retriever", "embedding", "reranker"}


def count_trajectories(spans: List[Dict[str, Any]]) -> int:
    """Number of distinct traces (conversations/turns) among the spans."""
    return len({s.get("trace_id") for s in spans if s.get("trace_id")})


def build_digest(spans: List[Dict[str, Any]], cap_chars: int = _DIGEST_CHAR_CAP) -> str:
    """Render spans as a compact, size-capped trajectory digest for the prompt.

    Framework-internal spans (span_kind not in _MEANINGFUL_KINDS) are dropped so
    the optimizer sees the agent's real behavior, not event-queue plumbing.
    """
    meaningful = [s for s in spans if (s.get("span_kind") or "").lower() in _MEANINGFUL_KINDS]
    lines: List[str] = []
    for s in meaningful or spans:
        attrs = s.get("attributes")
        if isinstance(attrs, str):
            attrs_str = attrs
        else:
            attrs_str = json.dumps(attrs) if attrs is not None else ""
        lines.append(f"[{s.get('start_time')}] {s.get('span_kind')} {s.get('name')} :: {attrs_str}")
    digest = "\n".join(lines)
    if len(digest) > cap_chars:
        digest = digest[:cap_chars] + "\n…[truncated]"
    return digest


def store_mcp_servers(store_url: str) -> Dict[str, Any]:
    """The skillberry-store control-plane MCP, in Claude Code format."""
    return {
        "skillberry-store": {
            "type": "sse",
            "url": store_url.rstrip("/") + _CONTROL_SSE_PATH,
        }
    }


def compose_dream_request(
    agent_name: str, namespace: str, digest: str, trajectory_count: int
) -> str:
    """Build the free-text task sent to ask-runspace (the whole prompt)."""
    return (
        f"You are running a skill 'dreaming' pass for agent '{agent_name}' "
        f"(namespace '{namespace}'). Below are the meaningful spans from "
        f"{trajectory_count} NEW trajectory(ies) since the last dream. Study where "
        f"the agent struggled, repeated work, or errored, and which skills were "
        f"involved.\n\n"
        f"Improve those skills via the skillberry-store MCP (mcp__skillberry-store__* "
        f"tools). Treat store objects as IMMUTABLE and git-like: reuse the involved "
        f"skill's same name so you always create a NEW VERSION (new UUID) of that "
        f"logical skill — never update in place, never invent a new name (no "
        f"*_optimized). Do what the trajectories call for: revise an involved skill, "
        f"add supporting snippets, or add a new skill. Record a short rationale. If "
        f"nothing warrants a change, make none and say so.\n\n"
        f"=== NEW TRAJECTORIES ===\n{digest}\n"
    )


# ---------------------------------------------------------------------------
# I/O: submit the run
# ---------------------------------------------------------------------------


async def submit_runspace_run(
    store_url: str, request_text: str, mcp_servers: Dict[str, Any]
) -> Dict[str, Any]:
    """POST the task to ask-runspace /run. Returns the parsed JSON (job_id, ...)."""
    url = store_url.rstrip("/") + _RUN_PATH
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"request": request_text, "mcp_servers": mcp_servers})
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def get_run_status(store_url: str, run_id: str) -> Dict[str, Any]:
    """Fetch a RunSpace dream run's status + summary from ask-runspace.

    Returns {status: pending|ready|failed, summary_md: str|None}.
    """
    # Fully-anchored allowlist on run_id *itself* (not a coerced copy) so the
    # value reaching the URL is provably free of URL-structural characters
    # (no '/', ':', '@', '?', '#', CR/LF) — closes the SSRF / path-traversal path.
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    safe_run_id = quote(run_id, safe="")
    url = store_url.rstrip("/") + "/plugins/ask-runspace/status/" + safe_run_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json() or {}
    return {"status": data.get("status"), "summary_md": data.get("summary_md")}


async def run_dream(
    kube, namespace: str, agent_name: str, store_url: str, phoenix_url: str
) -> Dict[str, Any]:
    """Run one dream pass for (namespace, agent).

    Reads NEW trajectory spans from Phoenix (only those newer than the watermark),
    and — if any exist — submits a RunSpace optimization run via the store's
    ask-runspace plugin. On submission the newest span consumed is recorded as a
    *pending* watermark; it is only committed once the run reaches ``ready`` (via
    the run-status poll), so a run that fails does not silently consume its
    trajectories. Returns a report dict.
    """
    cursor = dream_state.get_cursor(kube, namespace, agent_name)
    project = settings.dreaming_phoenix_project or agent_name
    spans = await fetch_new_spans(phoenix_url, project, cursor, settings.dreaming_max_events)
    if not spans:
        return {
            "status": "no_new_trajectories",
            "namespace": namespace,
            "agent": agent_name,
            "cursor": cursor,
            "new_trajectories": 0,
            "new_spans": 0,
        }

    new_trajectories = count_trajectories(spans)
    max_ts = max((s["start_time"] for s in spans if s.get("start_time")), default=None)
    digest = build_digest(spans)
    request_text = compose_dream_request(agent_name, namespace, digest, new_trajectories)
    mcp_servers = store_mcp_servers(store_url)

    result = await submit_runspace_run(store_url, request_text, mcp_servers)
    run_id = str(result.get("job_id") or result.get("data", {}).get("job_id") or "")

    if max_ts and run_id:
        dream_state.set_pending_cursor(kube, namespace, agent_name, max_ts, run_id)

    return {
        "status": "submitted",
        "namespace": namespace,
        "agent": agent_name,
        # A "trajectory" = one conversation/trace. Spans are the low-level steps
        # within it (a single turn emits many framework spans), so we report and
        # feed by trajectory to avoid the misleading raw span count.
        "new_trajectories": new_trajectories,
        "new_spans": len(spans),
        "cursor": max_ts,
        "run_id": run_id,
    }


def resolve_store_url(registry_url: Optional[str]) -> str:
    """Return the skillberry-store base URL from the auto-sync ConfigMap.

    ``registry_url`` is the auto-sync ConfigMap's ``registry-url`` — the in-cluster
    store address seeded when Rossoctl is installed with skills. Dreaming reuses it
    (the store hosts the ask-runspace plugin). Raises ValueError when absent.
    """
    if registry_url:
        return registry_url
    raise ValueError(
        "skillberry-store URL unknown: the skill auto-sync ConfigMap has no "
        "registry-url. Install Rossoctl with skills (or configure auto-sync) so the "
        "store address is known."
    )


def resolve_phoenix_url() -> str:
    """Return the Phoenix base URL (setting override, else in-cluster service)."""
    return settings.dreaming_phoenix_url or "http://phoenix.rossoctl-system.svc.cluster.local:6006"
