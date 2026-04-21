# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Loop Event Pipeline Consistency Test (via real API)

Sends a message through the backend streaming API, waits for completion,
then verifies that the history endpoint returns the same data needed for
the frontend to render AgentLoopCards.

Checks:
1. Streaming SSE events contain all expected types
2. History endpoint returns loop_events matching what was streamed
3. Reconstructed AgentLoop has tool_calls, tool_results, tokens, finalAnswer
4. tool_call count matches tool_result count

Environment:
  KAGENTI_UI_URL: Base URL (e.g. https://kagenti-ui-kagenti-system.apps....)
  KEYCLOAK_USER / KEYCLOAK_PASSWORD: Auth credentials
  KUBECONFIG: For kubectl access (fallback)

Run:
  KAGENTI_UI_URL=https://... KEYCLOAK_USER=admin KEYCLOAK_PASSWORD=... \
    python -m pytest tests/test_loop_event_pipeline.py -v
"""

import json
import os
import time
from urllib.parse import urlparse

import httpx
import pytest


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UI_URL = os.environ.get("KAGENTI_UI_URL", "")
KC_USER = os.environ.get("KEYCLOAK_USER", "admin")
KC_PASSWORD = os.environ.get("KEYCLOAK_PASSWORD", "")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"
NAMESPACE = "team1"
AGENT_NAME = "sandbox-legion"


def _skip_if_no_url():
    if not UI_URL:
        pytest.skip("Requires KAGENTI_UI_URL")
    if not KC_PASSWORD:
        pytest.skip("Requires KEYCLOAK_PASSWORD")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def get_keycloak_token() -> str:
    """Get an access token from Keycloak using password grant."""
    parsed = urlparse(UI_URL)
    # Keycloak route is typically keycloak-keycloak.<domain>
    domain = parsed.hostname
    if not domain:
        raise ValueError(f"Cannot parse domain from {UI_URL}")
    # Replace kagenti-ui-kagenti-system with keycloak-keycloak
    parts = domain.split(".")
    kc_host = "keycloak-keycloak." + ".".join(parts[1:])
    kc_url = f"https://{kc_host}"

    # Try realm + client combinations
    combos = [
        ("master", "admin-cli"),
        ("master", "kagenti-ui"),
        ("kagenti", "kagenti-ui"),
        ("kagenti", "admin-cli"),
    ]
    for realm, client_id in combos:
        token_url = f"{kc_url}/realms/{realm}/protocol/openid-connect/token"
        try:
            resp = httpx.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "username": KC_USER,
                    "password": KC_PASSWORD,
                },
                verify=VERIFY_SSL,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "access_token" in data:
                    return data["access_token"]
        except Exception:
            continue

    raise RuntimeError(f"Failed to get Keycloak token from {kc_url}")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def api_url(path: str) -> str:
    """Build full API URL."""
    return f"{UI_URL}/api/v1{path}"


def send_streaming_message(token: str, context_id: str, message: str) -> list[dict]:
    """Send a message via streaming API, collect all loop events."""
    loop_events: list[dict] = []

    with httpx.Client(timeout=180, verify=VERIFY_SSL) as client:
        with client.stream(
            "POST",
            api_url(f"/sandbox/{NAMESPACE}/chat/stream"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "message": message,
                "context_id": context_id,
                "agent_name": AGENT_NAME,
            },
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            for chunk in resp.iter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:].strip())
                        if "loop_event" in data:
                            loop_events.append(data["loop_event"])
                    except (json.JSONDecodeError, TypeError):
                        pass

    return loop_events


def get_history(token: str, context_id: str) -> dict:
    """Fetch session history from the API."""
    resp = httpx.get(
        api_url(f"/sandbox/{NAMESPACE}/sessions/{context_id}/history?limit=50"),
        headers={"Authorization": f"Bearer {token}"},
        verify=VERIFY_SSL,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Reconstruction (mirrors frontend loadInitialHistory logic)
# ---------------------------------------------------------------------------


def reconstruct_loops(events: list[dict]) -> dict[str, dict]:
    """Simulate frontend AgentLoop reconstruction from loop_events."""
    loops: dict[str, dict] = {}

    for le in events:
        lid = le.get("loop_id", "unknown")
        if lid not in loops:
            loops[lid] = {
                "id": lid,
                "steps": {},
                "status": "planning",
                "plan": [],
                "finalAnswer": "",
            }
        loop = loops[lid]
        et = le.get("type", "")

        if et == "planner_output":
            loop["plan"] = le.get("steps", [])
            loop["status"] = "planning"
        elif et == "executor_step":
            si = le.get("step", 0)
            existing = loop["steps"].get(
                si, {"toolCalls": [], "toolResults": [], "status": "running"}
            )
            loop["steps"][si] = {
                "index": si,
                "description": le.get("description", "") or existing.get("description", ""),
                "reasoning": le.get("reasoning", "") or existing.get("reasoning", ""),
                "tokens": {
                    "prompt": le.get("prompt_tokens", 0)
                    or existing.get("tokens", {}).get("prompt", 0),
                    "completion": le.get("completion_tokens", 0)
                    or existing.get("tokens", {}).get("completion", 0),
                },
                "toolCalls": existing.get("toolCalls", []),
                "toolResults": existing.get("toolResults", []),
                "status": existing.get("status", "running"),
            }
            loop["status"] = "executing"
        elif et == "tool_call":
            si = le.get("step", 0)
            if si in loop["steps"]:
                loop["steps"][si]["toolCalls"].extend(le.get("tools", []))
        elif et == "tool_result":
            si = le.get("step", 0)
            if si in loop["steps"]:
                loop["steps"][si]["toolResults"].append(
                    {
                        "name": le.get("name", ""),
                        "output": le.get("output", ""),
                    }
                )
                loop["steps"][si]["status"] = "done"
        elif et == "micro_reasoning":
            si = le.get("step", 0)
            if si in loop["steps"]:
                if "microReasonings" not in loop["steps"][si]:
                    loop["steps"][si]["microReasonings"] = []
                loop["steps"][si]["microReasonings"].append(
                    {
                        "type": "micro_reasoning",
                        "micro_step": le.get("micro_step", 0),
                        "reasoning": le.get("reasoning", ""),
                        "next_action": le.get("next_action", ""),
                        "model": le.get("model", ""),
                        "prompt_tokens": le.get("prompt_tokens", 0),
                        "completion_tokens": le.get("completion_tokens", 0),
                        "system_prompt": le.get("system_prompt", ""),
                        "prompt_messages": le.get("prompt_messages", []),
                    }
                )
        elif et == "reflector_decision":
            loop["status"] = "reflecting"
        elif et == "reporter_output":
            loop["status"] = "done"
            loop["finalAnswer"] = le.get("content", "")

    # Mark all as done (historical)
    for loop in loops.values():
        if loop["status"] != "done":
            loop["status"] = "done"
        for s in loop["steps"].values():
            if s["status"] == "running":
                s["status"] = "done"

    return loops


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def auth_token():
    _skip_if_no_url()
    return get_keycloak_token()


@pytest.fixture(scope="module")
def session_data(auth_token):
    """Send a message and capture both streaming events and history."""
    context_id = f"pipeline-test-{int(time.time())}-{os.urandom(4).hex()}"

    # Step 1: Send message via streaming API, capture SSE loop events
    streaming_events = send_streaming_message(
        auth_token,
        context_id,
        "Create a file called /workspace/pipeline-test.txt with 'hello pipeline' and then read it back",
    )

    # Step 2: Wait for persistence
    time.sleep(3)

    # Step 3: Fetch history
    history = get_history(auth_token, context_id)

    return {
        "context_id": context_id,
        "streaming_events": streaming_events,
        "history": history,
        "history_loop_events": history.get("loop_events", []),
    }


class TestLoopEventPipelineAPI:
    """End-to-end pipeline test via real API."""

    def test_streaming_has_events(self, session_data):
        """Streaming SSE should produce loop events."""
        events = session_data["streaming_events"]
        assert len(events) > 0, "No loop events received from streaming"
        types = {e.get("type") for e in events}
        print(f"Streaming event types: {types}")
        assert "planner_output" in types
        assert "executor_step" in types

    def test_streaming_has_tool_calls(self, session_data):
        """Streaming should include tool_call events."""
        events = session_data["streaming_events"]
        tool_calls = [e for e in events if e.get("type") == "tool_call"]
        assert len(tool_calls) > 0, f"No tool_call events. Types: {[e.get('type') for e in events]}"
        for tc in tool_calls:
            tools = tc.get("tools", [])
            assert len(tools) > 0, "tool_call has empty tools array"
            assert tools[0].get("name"), "tool missing name"

    def test_streaming_has_reporter(self, session_data):
        """Streaming should end with reporter_output."""
        events = session_data["streaming_events"]
        reporters = [e for e in events if e.get("type") == "reporter_output"]
        assert len(reporters) > 0, "No reporter_output event"
        assert reporters[-1].get("content"), "reporter_output has no content"

    def test_history_has_loop_events(self, session_data):
        """History endpoint should return loop_events."""
        le = session_data["history_loop_events"]
        assert len(le) > 0, "History has no loop_events"

    def test_history_matches_streaming(self, session_data):
        """History loop_events should match streaming events."""
        streaming = session_data["streaming_events"]
        history = session_data["history_loop_events"]

        s_types = [e.get("type") for e in streaming]
        h_types = [e.get("type") for e in history]

        print(f"Streaming types: {s_types}")
        print(f"History types:   {h_types}")

        # History should have the same event types
        assert set(h_types) == set(s_types), (
            f"Type mismatch: streaming={set(s_types)}, history={set(h_types)}"
        )
        # Same count (no lost events)
        assert len(history) == len(streaming), (
            f"Event count mismatch: streaming={len(streaming)}, history={len(history)}"
        )

    def test_reconstruction_from_history(self, session_data):
        """Reconstructed loops from history should have tool data."""
        le = session_data["history_loop_events"]
        loops = reconstruct_loops(le)

        assert len(loops) > 0, "No loops reconstructed"

        for lid, loop in loops.items():
            assert loop["status"] == "done", f"Loop {lid} not done"
            assert loop["finalAnswer"], f"Loop {lid} no finalAnswer"

            total_tc = sum(len(s["toolCalls"]) for s in loop["steps"].values())
            total_tr = sum(len(s["toolResults"]) for s in loop["steps"].values())
            assert total_tc > 0, f"Loop {lid}: 0 tool_calls after reconstruction"
            assert total_tr > 0, f"Loop {lid}: 0 tool_results after reconstruction"
            assert total_tc == total_tr, (
                f"Loop {lid}: tool_calls={total_tc} != tool_results={total_tr}"
            )

    def test_reconstruction_from_streaming(self, session_data):
        """Reconstructed loops from streaming should match history reconstruction."""
        s_loops = reconstruct_loops(session_data["streaming_events"])
        h_loops = reconstruct_loops(session_data["history_loop_events"])

        assert set(s_loops.keys()) == set(h_loops.keys()), "Loop IDs differ"

        for lid in s_loops:
            sl = s_loops[lid]
            hl = h_loops[lid]
            assert sl["status"] == hl["status"], f"Status: {sl['status']} vs {hl['status']}"
            assert len(sl["steps"]) == len(hl["steps"]), "Step count differs"

            for si in sl["steps"]:
                ss = sl["steps"][si]
                hs = hl["steps"][si]
                assert len(ss["toolCalls"]) == len(hs["toolCalls"]), (
                    f"Step {si} toolCalls: streaming={len(ss['toolCalls'])}, history={len(hs['toolCalls'])}"
                )
                assert len(ss["toolResults"]) == len(hs["toolResults"]), (
                    f"Step {si} toolResults: streaming={len(ss['toolResults'])}, history={len(hs['toolResults'])}"
                )
