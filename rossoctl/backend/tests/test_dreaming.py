# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for the skill dreaming service (pure helpers + orchestration).

Trajectories are read from Phoenix (per-agent project spans); the watermark is a
span-startTime cursor persisted in a ConfigMap (mocked here).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import dreaming


def _span_node(name, ts, kind="LLM", attrs=None):
    return {
        "node": {
            "name": name,
            "spanKind": kind,
            "startTime": ts,
            "attributes": attrs if attrs is not None else json.dumps({"llm.output": "hi"}),
        }
    }


def _phoenix_response(project, span_nodes):
    return {
        "data": {
            "projects": {
                "edges": [
                    {"node": {"name": project, "spans": {"edges": span_nodes}}},
                    {"node": {"name": "other-agent", "spans": {"edges": []}}},
                ]
            }
        }
    }


class TestParseTs:
    def test_handles_zulu(self):
        assert dreaming._parse_ts("2026-07-14T10:00:00Z") is not None

    def test_bad_value_is_none(self):
        assert dreaming._parse_ts("nonsense") is None
        assert dreaming._parse_ts(None) is None


class TestBuildDigest:
    def test_renders_spans(self):
        spans = [
            {
                "name": "weather.call",
                "span_kind": "TOOL",
                "start_time": "2026-07-14T10:00:00Z",
                "attributes": json.dumps({"input": "weather?"}),
            },
        ]
        digest = dreaming.build_digest(spans)
        assert "weather.call" in digest and "TOOL" in digest and "weather?" in digest

    def test_respects_char_cap(self):
        spans = [
            {"name": "s", "span_kind": "LLM", "start_time": "t", "attributes": "x" * 1000}
            for _ in range(50)
        ]
        digest = dreaming.build_digest(spans, cap_chars=300)
        assert len(digest) <= 300 + len("\n…[truncated]")
        assert digest.endswith("…[truncated]")


class TestStoreMcpServers:
    def test_builds_sse_control_url(self):
        mcp = dreaming.store_mcp_servers("http://skillberry-store:8000/")
        assert mcp["skillberry-store"]["url"] == "http://skillberry-store:8000/control_sse"
        assert mcp["skillberry-store"]["type"] == "sse"


class TestComposeRequest:
    def test_immutable_versioning_same_name(self):
        req = dreaming.compose_dream_request("weather", "team1", "DIGEST", 3)
        assert "weather" in req and "team1" in req
        # Immutable, git-like versioning under the same name (not "in place").
        assert "IMMUTABLE" in req and "NEW VERSION" in req and "same name" in req
        assert "_optimized" in req  # forbids inventing a new name
        assert "DIGEST" in req and "3 NEW" in req


class TestResolveUrls:
    def test_store_url_from_configmap(self):
        assert dreaming.resolve_store_url("http://store:8000") == "http://store:8000"

    def test_store_url_raises_when_absent(self):
        with pytest.raises(ValueError):
            dreaming.resolve_store_url(None)

    def test_phoenix_url_default(self):
        with patch.object(dreaming.settings, "dreaming_phoenix_url", ""):
            assert "phoenix" in dreaming.resolve_phoenix_url()

    def test_phoenix_url_override(self):
        with patch.object(dreaming.settings, "dreaming_phoenix_url", "http://px:6006"):
            assert dreaming.resolve_phoenix_url() == "http://px:6006"


@pytest.mark.asyncio
class TestFetchNewSpans:
    async def _mock_post(self, payload):
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status = MagicMock()
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    async def test_filters_by_project_and_watermark(self):
        payload = _phoenix_response(
            "weather",
            [
                _span_node("old", "2026-07-14T09:00:00Z"),
                _span_node("new1", "2026-07-14T11:00:00Z"),
                _span_node("new2", "2026-07-14T12:00:00Z"),
            ],
        )
        with patch("httpx.AsyncClient", return_value=await self._mock_post(payload)):
            spans = await dreaming.fetch_new_spans(
                "http://px:6006", "weather", "2026-07-14T10:00:00Z", 100
            )
        names = [s["name"] for s in spans]
        assert names == ["new1", "new2"]  # old filtered out, ascending order

    async def test_none_cursor_keeps_all_for_project(self):
        payload = _phoenix_response(
            "weather",
            [
                _span_node("a", "2026-07-14T09:00:00Z"),
                _span_node("b", "2026-07-14T10:00:00Z"),
            ],
        )
        with patch("httpx.AsyncClient", return_value=await self._mock_post(payload)):
            spans = await dreaming.fetch_new_spans("http://px:6006", "weather", None, 100)
        assert len(spans) == 2

    async def test_unknown_project_returns_empty(self):
        payload = _phoenix_response("weather", [_span_node("a", "2026-07-14T09:00:00Z")])
        with patch("httpx.AsyncClient", return_value=await self._mock_post(payload)):
            spans = await dreaming.fetch_new_spans("http://px:6006", "nope", None, 100)
        assert spans == []


@pytest.mark.asyncio
class TestRunDream:
    async def test_no_new_short_circuits(self):
        with (
            patch.object(dreaming.dream_state, "get_cursor", return_value=None),
            patch.object(dreaming, "fetch_new_spans", AsyncMock(return_value=[])),
            patch.object(dreaming, "submit_runspace_run", AsyncMock()) as submit,
            patch.object(dreaming.dream_state, "set_pending_cursor") as pending,
        ):
            report = await dreaming.run_dream(
                None, "team1", "weather", "http://store:8000", "http://px:6006"
            )
        assert report["status"] == "no_new_trajectories" and report["new_spans"] == 0
        submit.assert_not_called()
        pending.assert_not_called()

    async def test_submits_and_sets_pending_to_newest(self):
        spans = [
            {
                "name": "a",
                "span_kind": "LLM",
                "start_time": "2026-07-14T10:00:00Z",
                "attributes": "{}",
            },
            {
                "name": "c",
                "span_kind": "LLM",
                "start_time": "2026-07-14T10:05:00Z",
                "attributes": "{}",
            },
        ]
        with (
            patch.object(dreaming.dream_state, "get_cursor", return_value=None),
            patch.object(dreaming, "fetch_new_spans", AsyncMock(return_value=spans)),
            patch.object(
                dreaming, "submit_runspace_run", AsyncMock(return_value={"job_id": "job-42"})
            ) as submit,
            patch.object(dreaming.dream_state, "set_pending_cursor") as pending,
        ):
            report = await dreaming.run_dream(
                None, "team1", "weather", "http://store:8000", "http://px:6006"
            )
        assert report["status"] == "submitted" and report["run_id"] == "job-42"
        assert report["new_spans"] == 2
        assert report["cursor"] == "2026-07-14T10:05:00Z"
        submit.assert_awaited_once()
        # Watermark is only *pending* on submission (committed later when ready).
        args = pending.call_args.args
        assert args[1] == "team1" and args[2] == "weather" and args[3] == "2026-07-14T10:05:00Z"

    async def test_reads_nested_job_id(self):
        spans = [
            {
                "name": "a",
                "span_kind": "LLM",
                "start_time": "2026-07-14T10:00:00Z",
                "attributes": "{}",
            }
        ]
        with (
            patch.object(dreaming.dream_state, "get_cursor", return_value=None),
            patch.object(dreaming, "fetch_new_spans", AsyncMock(return_value=spans)),
            patch.object(
                dreaming,
                "submit_runspace_run",
                AsyncMock(return_value={"data": {"job_id": "nested-7"}}),
            ),
            patch.object(dreaming.dream_state, "set_pending_cursor"),
        ):
            report = await dreaming.run_dream(
                None, "team1", "weather", "http://store:8000", "http://px:6006"
            )
        assert report["run_id"] == "nested-7"


@pytest.mark.asyncio
class TestGetRunStatus:
    async def test_rejects_malicious_run_id(self):
        # A run id that could steer the request URL must be refused (SSRF guard).
        for bad in ["../../evil", "a/b", "http://evil", "job 42", "job\n42", "job\r"]:
            with pytest.raises(ValueError):
                await dreaming.get_run_status("http://store:8000", bad)

    async def test_accepts_opaque_run_id(self):
        resp = MagicMock()
        resp.json.return_value = {"status": "ready", "summary_md": "done"}
        resp.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=ctx):
            out = await dreaming.get_run_status("http://store:8000", "job-42")
        assert out["status"] == "ready" and out["summary_md"] == "done"


class TestPendingCursor:
    """Watermark is committed on 'ready', dropped on failure (not on submission)."""

    def _state_store(self, initial=None):
        state = dict(initial or {})

        def _get_state(kube, ns, agent):
            return dict(state) if state else None

        def _write(kube, ns, agent, entry):
            state.clear()
            state.update(entry)

        return state, _get_state, _write

    def test_commit_advances_only_matching_run(self):
        from app.services import dream_state

        state, get_state, write = self._state_store(
            {"pending_ts": "2026-07-14T10:05:00Z", "pending_run_id": "job-42"}
        )
        with (
            patch.object(dream_state, "get_state", get_state),
            patch.object(dream_state, "_write_entry", write),
        ):
            assert dream_state.commit_pending_cursor(None, "team1", "weather", "other") is False
            assert dream_state.commit_pending_cursor(None, "team1", "weather", "job-42") is True
        assert state["last_dreamed_ts"] == "2026-07-14T10:05:00Z"
        assert state["dreamed_count"] == 1
        assert "pending_ts" not in state and "pending_run_id" not in state

    def test_clear_drops_pending_on_failure(self):
        from app.services import dream_state

        state, get_state, write = self._state_store(
            {"pending_ts": "2026-07-14T10:05:00Z", "pending_run_id": "job-42"}
        )
        with (
            patch.object(dream_state, "get_state", get_state),
            patch.object(dream_state, "_write_entry", write),
        ):
            dream_state.clear_pending_cursor(None, "team1", "weather", "job-42")
        assert "pending_ts" not in state
        assert "last_dreamed_ts" not in state  # failed run consumed nothing

    def test_max_ts_handles_mixed_offsets(self):
        from app.services import dream_state

        # +00:00 and Z forms of the same instant order correctly; later wins.
        assert dream_state._max_ts("2026-07-14T10:00:00+00:00", "2026-07-14T10:00:00Z") == (
            "2026-07-14T10:00:00+00:00"
        )
        assert (
            dream_state._max_ts("2026-07-14T10:00:00Z", "2026-07-14T11:00:00+00:00")
            == "2026-07-14T11:00:00+00:00"
        )


class TestScheduleThresholds:
    """Auto-dream schedule (weekday + time) is persisted alongside count thresholds."""

    def test_set_thresholds_persists_schedule(self):
        from app.services import dream_state

        captured = {}

        def _fake_write(kube, ns, agent, entry):
            captured.update(entry)

        with (
            patch.object(dream_state, "get_state", return_value={}),
            patch.object(dream_state, "_write_entry", _fake_write),
        ):
            dream_state.set_thresholds(
                None,
                "team1",
                "weather",
                min_new_trajectories=5,
                min_interval_seconds=0,
                schedule_days=["sun", "mon"],
                schedule_time="09:30",
            )

        assert captured["min_new_trajectories"] == 5
        assert captured["schedule_days"] == ["sun", "mon"]
        assert captured["schedule_time"] == "09:30"

    def test_set_thresholds_defaults_empty_schedule(self):
        from app.services import dream_state

        captured = {}
        with (
            patch.object(dream_state, "get_state", return_value={}),
            patch.object(dream_state, "_write_entry", lambda k, n, a, e: captured.update(e)),
        ):
            dream_state.set_thresholds(None, "team1", "weather", 0, 0)

        assert captured["schedule_days"] == []
        assert captured["schedule_time"] == ""
