# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Loop Event Pipeline Consistency Test

Verifies that the loop_events stored in the DB contain all data needed
for the frontend to render AgentLoopCards identically to the streaming view.

Checks:
1. All expected event types are present (planner, executor, reflector, reporter)
2. tool_call events have tools array with name and args
3. tool_result events have name and output
4. executor_step events have description and tokens
5. Reconstructed AgentLoop has matching structure

Run:
  KUBECONFIG=~/clusters/hcp/.../kubeconfig python -m pytest tests/test_loop_event_pipeline.py -v
"""

import asyncio
import json
import os
import subprocess
import pytest


def get_session_pool_sync(namespace: str):
    """Get a DB connection by running psql via kubectl."""
    kubeconfig = os.environ.get("KUBECONFIG", "")
    kubectl = "/opt/homebrew/bin/oc" if os.path.exists("/opt/homebrew/bin/oc") else "kubectl"

    def query(sql: str) -> str:
        cmd = (
            f"KUBECONFIG={kubeconfig} {kubectl} exec -n {namespace} postgres-sessions-0 "
            f'-- psql -U kagenti -d sessions -t -A -c "{sql}"'
        )
        return subprocess.check_output(cmd, shell=True, timeout=15).decode().strip()

    return query


@pytest.fixture
def db_query():
    """Fixture providing a DB query function."""
    return get_session_pool_sync("team1")


def reconstruct_loop(events: list[dict]) -> dict:
    """Simulate frontend loadInitialHistory reconstruction."""
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
                "totalSteps": 0,
                "model": "",
            }
        loop = loops[lid]
        et = le.get("type", "")

        if et == "planner_output":
            loop["plan"] = le.get("steps", [])
            loop["status"] = "planning"
            loop["model"] = le.get("model", loop["model"])
        elif et == "executor_step":
            si = le.get("step", 0)
            existing = loop["steps"].get(
                si, {"toolCalls": [], "toolResults": [], "status": "running"}
            )
            desc = le.get("description", "")
            loop["steps"][si] = {
                "index": si,
                "description": desc or existing.get("description", ""),
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
                "nodeType": "executor",
            }
            loop["status"] = "executing"
            loop["totalSteps"] = le.get("total_steps", loop["totalSteps"])
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


class TestLoopEventPipeline:
    """Test that persisted loop_events contain complete data for UI rendering."""

    def test_recent_sessions_have_loop_events(self, db_query):
        """At least one recent session has loop_events."""
        result = db_query("SELECT count(*) FROM tasks WHERE metadata::text LIKE '%loop_events%'")
        assert int(result) > 0, "No sessions with loop_events found"

    def test_event_types_complete(self, db_query):
        """Loop events contain all required types."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%loop_events%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)
        types = {e.get("type") for e in events}

        assert "planner_output" in types, f"Missing planner_output. Types: {types}"
        assert "executor_step" in types, f"Missing executor_step. Types: {types}"
        assert "reflector_decision" in types, f"Missing reflector_decision. Types: {types}"
        assert "reporter_output" in types, f"Missing reporter_output. Types: {types}"

    def test_tool_call_events_have_tools(self, db_query):
        """tool_call events contain tools array with name."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%tool_call%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)
        tool_calls = [e for e in events if e.get("type") == "tool_call"]

        assert len(tool_calls) > 0, "No tool_call events found"
        for tc in tool_calls:
            tools = tc.get("tools", [])
            assert len(tools) > 0, f"tool_call has empty tools array: {tc}"
            for tool in tools:
                assert "name" in tool, f"Tool missing name: {tool}"

    def test_tool_result_events_have_output(self, db_query):
        """tool_result events contain name and output."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%tool_result%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)
        results = [e for e in events if e.get("type") == "tool_result"]

        assert len(results) > 0, "No tool_result events found"
        for tr in results:
            assert "name" in tr, f"tool_result missing name: {tr}"
            assert "output" in tr, f"tool_result missing output: {tr}"

    def test_executor_step_has_tokens(self, db_query):
        """executor_step events have token counts."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%loop_events%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)
        steps = [e for e in events if e.get("type") == "executor_step"]

        assert len(steps) > 0, "No executor_step events found"
        # At least one step should have tokens
        has_tokens = any(
            e.get("prompt_tokens", 0) > 0 or e.get("completion_tokens", 0) > 0 for e in steps
        )
        assert has_tokens, "No executor_step has tokens"

    def test_reconstruction_produces_valid_loop(self, db_query):
        """Reconstructed AgentLoop has all expected fields."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%tool_call%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)
        loops = reconstruct_loop(events)

        assert len(loops) > 0, "No loops reconstructed"

        for lid, loop in loops.items():
            assert loop["status"] == "done", f"Loop {lid} status={loop['status']}"
            assert len(loop["steps"]) > 0, f"Loop {lid} has no steps"

            total_tool_calls = sum(len(s["toolCalls"]) for s in loop["steps"].values())
            total_tool_results = sum(len(s["toolResults"]) for s in loop["steps"].values())

            assert total_tool_calls > 0, f"Loop {lid} has 0 tool_calls after reconstruction"
            assert total_tool_results > 0, f"Loop {lid} has 0 tool_results after reconstruction"
            assert loop["finalAnswer"], f"Loop {lid} has no finalAnswer"

            # Every step should be done
            for si, step in loop["steps"].items():
                assert step["status"] == "done", f"Step {si} status={step['status']}"

    def test_tool_call_count_matches_results(self, db_query):
        """Number of tool_call events matches tool_result events."""
        result = db_query(
            "SELECT metadata::json->'loop_events' FROM tasks "
            "WHERE metadata::text LIKE '%tool_call%' "
            "ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC LIMIT 1"
        )
        events = json.loads(result)

        call_count = sum(len(e.get("tools", [])) for e in events if e.get("type") == "tool_call")
        result_count = len([e for e in events if e.get("type") == "tool_result"])

        assert call_count == result_count, (
            f"tool_call count ({call_count}) != tool_result count ({result_count})"
        )
