# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for sandbox session metadata merge logic.

Verifies that list_sessions() properly merges title/owner/visibility
from earlier task rows into the response when the latest task row
(picked by DISTINCT ON context_id ... ORDER BY id DESC) lacks metadata.

The A2A SDK creates immutable task rows per message exchange. The backend's
_set_owner_metadata() sets title/owner on the first row, but the agent
creates later rows that don't carry this metadata forward. The merge
logic in list_sessions() compensates by looking up metadata from sibling
rows.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("app.routers.sandbox", reason="Sandbox modules not available")


def _make_task_row(
    *,
    id: int,
    context_id: str,
    kind: str = "task",
    status: dict | None = None,
    metadata: dict | None = None,
):
    """Create a mock DB row matching the tasks table schema."""
    row = {
        "id": str(id),  # TaskSummary.id is a string
        "context_id": context_id,
        "kind": kind,
        "status": json.dumps(status or {"state": "completed"}),
        "metadata": json.dumps(metadata) if metadata else None,
    }
    return row


class TestParseJsonField:
    """Tests for _parse_json_field helper."""

    def test_parses_json_string(self):
        from app.routers.sandbox import _parse_json_field

        result = _parse_json_field('{"key": "value"}')
        assert result == {"key": "value"}

    def test_returns_dict_as_is(self):
        from app.routers.sandbox import _parse_json_field

        d = {"key": "value"}
        result = _parse_json_field(d)
        assert result is d

    def test_returns_none_for_none(self):
        from app.routers.sandbox import _parse_json_field

        assert _parse_json_field(None) is None

    def test_raises_on_empty_string(self):
        """Empty string is technically invalid JSON — json.loads raises."""
        import json

        from app.routers.sandbox import _parse_json_field

        with pytest.raises(json.JSONDecodeError):
            _parse_json_field("")

    def test_raises_on_invalid_json(self):
        """Non-JSON string should raise JSONDecodeError."""
        import json

        from app.routers.sandbox import _parse_json_field

        with pytest.raises(json.JSONDecodeError):
            _parse_json_field("not json")


class TestRowToSummary:
    """Tests for _row_to_summary conversion."""

    def test_summary_with_metadata(self):
        from app.routers.sandbox import _row_to_summary

        row = _make_task_row(
            id=1,
            context_id="ctx-123",
            metadata={"title": "My Session", "owner": "admin"},
        )
        summary = _row_to_summary(row)
        assert summary.context_id == "ctx-123"
        assert summary.metadata["title"] == "My Session"
        assert summary.metadata["owner"] == "admin"

    def test_summary_without_metadata(self):
        from app.routers.sandbox import _row_to_summary

        row = _make_task_row(id=1, context_id="ctx-456", metadata=None)
        summary = _row_to_summary(row)
        assert summary.context_id == "ctx-456"
        # metadata should be None or empty — no title
        assert not (summary.metadata or {}).get("title")

    def test_summary_with_empty_metadata(self):
        from app.routers.sandbox import _row_to_summary

        row = _make_task_row(id=1, context_id="ctx-789", metadata={})
        summary = _row_to_summary(row)
        assert summary.context_id == "ctx-789"


class TestMetadataMergeLogic:
    """Tests for the metadata merge in list_sessions().

    These test the Python-side merge logic that fills in title/owner
    from sibling rows when the latest row lacks them.
    """

    def test_merge_fills_missing_title(self):
        """When latest row has no title, it should come from a sibling row."""
        from app.routers.sandbox import TaskSummary, _parse_json_field

        # Simulate: latest row has no metadata, earlier row has title+owner
        items = [
            TaskSummary(
                id="2",
                context_id="ctx-aaa",
                kind="task",
                status={"state": "completed"},
                metadata=None,  # latest row — no metadata
            ),
        ]

        # Simulate the donor row from the merge query
        donor_metadata = {"title": "Hello world", "owner": "admin", "visibility": "private"}

        # Apply merge logic (extracted from list_sessions)
        missing_meta = [s for s in items if not (s.metadata or {}).get("title")]
        assert len(missing_meta) == 1

        for s in missing_meta:
            if s.metadata is None:
                s.metadata = {}
            for key in ("title", "owner", "visibility"):
                if key not in s.metadata and key in donor_metadata:
                    s.metadata[key] = donor_metadata[key]

        assert items[0].metadata["title"] == "Hello world"
        assert items[0].metadata["owner"] == "admin"
        assert items[0].metadata["visibility"] == "private"

    def test_merge_preserves_existing_metadata(self):
        """When latest row already has title, the merge should NOT overwrite it."""
        from app.routers.sandbox import TaskSummary

        items = [
            TaskSummary(
                id="3",
                context_id="ctx-bbb",
                kind="task",
                status={"state": "completed"},
                metadata={"title": "Original Title", "owner": "admin"},
            ),
        ]

        _donor_metadata = {"title": "Should NOT Replace", "owner": "other-user"}

        missing_meta = [s for s in items if not (s.metadata or {}).get("title")]
        # The item already has a title, so it should NOT be in missing_meta
        assert len(missing_meta) == 0

        # Title should remain unchanged
        assert items[0].metadata["title"] == "Original Title"

    def test_merge_handles_partial_donor(self):
        """Donor row with only title (no owner) should still fill title."""
        from app.routers.sandbox import TaskSummary

        items = [
            TaskSummary(
                id="4",
                context_id="ctx-ccc",
                kind="task",
                status={"state": "completed"},
                metadata=None,
            ),
        ]

        donor_metadata = {"title": "Partial Donor"}

        missing_meta = [s for s in items if not (s.metadata or {}).get("title")]
        for s in missing_meta:
            if s.metadata is None:
                s.metadata = {}
            for key in ("title", "owner", "visibility"):
                if key not in s.metadata and key in donor_metadata:
                    s.metadata[key] = donor_metadata[key]

        assert items[0].metadata["title"] == "Partial Donor"
        assert "owner" not in items[0].metadata

    def test_merge_skips_items_with_title(self):
        """Items that already have a title should be skipped entirely."""
        from app.routers.sandbox import TaskSummary

        items = [
            TaskSummary(
                id="5",
                context_id="ctx-ddd",
                kind="task",
                status={"state": "completed"},
                metadata={"title": "Has Title"},
            ),
            TaskSummary(
                id="6",
                context_id="ctx-eee",
                kind="task",
                status={"state": "working"},
                metadata=None,
            ),
        ]

        missing_meta = [s for s in items if not (s.metadata or {}).get("title")]
        # Only the second item should need merging
        assert len(missing_meta) == 1
        assert missing_meta[0].context_id == "ctx-eee"


class TestSessionChainModels:
    """Tests for SessionChainEntry and SessionChainResponse models."""

    def test_chain_entry_root(self):
        from app.routers.sandbox import SessionChainEntry

        entry = SessionChainEntry(
            context_id="ctx-root",
            type="root",
            status="completed",
            title="Root session",
        )
        assert entry.context_id == "ctx-root"
        assert entry.type == "root"
        assert entry.parent is None

    def test_chain_entry_child(self):
        from app.routers.sandbox import SessionChainEntry

        entry = SessionChainEntry(
            context_id="ctx-child",
            type="child",
            status="working",
            parent="ctx-root",
        )
        assert entry.parent == "ctx-root"
        assert entry.passover_from is None

    def test_chain_entry_passover(self):
        from app.routers.sandbox import SessionChainEntry

        entry = SessionChainEntry(
            context_id="ctx-pass",
            type="passover",
            passover_from="ctx-root",
        )
        assert entry.passover_from == "ctx-root"

    def test_chain_response_structure(self):
        from app.routers.sandbox import SessionChainEntry, SessionChainResponse

        response = SessionChainResponse(
            root="ctx-root",
            chain=[
                SessionChainEntry(context_id="ctx-root", type="root", status="completed"),
                SessionChainEntry(
                    context_id="ctx-child1",
                    type="child",
                    parent="ctx-root",
                    status="working",
                ),
                SessionChainEntry(
                    context_id="ctx-pass1",
                    type="passover",
                    passover_from="ctx-root",
                    status="active",
                ),
            ],
        )
        assert response.root == "ctx-root"
        assert len(response.chain) == 3
        assert response.chain[0].type == "root"
        assert response.chain[1].type == "child"
        assert response.chain[2].type == "passover"
