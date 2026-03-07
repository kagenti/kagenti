"""Tests for tofu.py — Trust-On-First-Use config integrity verification."""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from tofu import TofuVerifier


class TestHashFile:
    """Test file hashing."""

    def test_hash_existing_file(self, tmp_workspace):
        v = TofuVerifier(str(tmp_workspace))
        h = v._hash_file(tmp_workspace / "CLAUDE.md")
        expected = hashlib.sha256(
            (tmp_workspace / "CLAUDE.md").read_bytes()
        ).hexdigest()
        assert h == expected

    def test_hash_missing_file(self, tmp_workspace):
        v = TofuVerifier(str(tmp_workspace))
        h = v._hash_file(tmp_workspace / "nonexistent.txt")
        assert h is None


class TestComputeHashes:
    """Test hash computation for tracked files."""

    def test_computes_all_tracked(self, tmp_workspace):
        v = TofuVerifier(str(tmp_workspace))
        hashes = v.compute_hashes()
        assert "CLAUDE.md" in hashes
        assert ".claude/settings.json" in hashes
        assert "sources.json" in hashes
        # CLAUDE.md and sources.json exist, should have hashes
        assert hashes["CLAUDE.md"] is not None
        assert hashes["sources.json"] is not None

    def test_missing_file_returns_none(self, tmp_path):
        """Workspace without any tracked files returns None values."""
        empty_ws = tmp_path / "empty"
        empty_ws.mkdir()
        v = TofuVerifier(str(empty_ws))
        hashes = v.compute_hashes()
        assert all(h is None for h in hashes.values())


class TestVerifyOrInitialize:
    """Test the verify/initialize flow."""

    def test_first_run_initializes(self, tmp_workspace):
        """First run (no ConfigMap) should store hashes and return True."""
        v = TofuVerifier(str(tmp_workspace), namespace="test-ns")

        with patch.object(v, "get_stored_hashes", return_value=None):
            with patch.object(v, "store_hashes") as mock_store:
                ok, msg = v.verify_or_initialize()
                assert ok is True
                assert "initialized" in msg.lower()
                mock_store.assert_called_once()

    def test_verify_match(self, tmp_workspace):
        """Hashes match stored → return (True, 'verified')."""
        v = TofuVerifier(str(tmp_workspace))
        current = v.compute_hashes()

        with patch.object(v, "get_stored_hashes", return_value=current):
            ok, msg = v.verify_or_initialize()
            assert ok is True
            assert "verified" in msg.lower()

    def test_verify_mismatch(self, tmp_workspace):
        """Changed file → return (False, 'FAILED: CHANGED')."""
        v = TofuVerifier(str(tmp_workspace))
        stored = v.compute_hashes()

        # Modify CLAUDE.md
        (tmp_workspace / "CLAUDE.md").write_text("MODIFIED CONTENT")

        with patch.object(v, "get_stored_hashes", return_value=stored):
            ok, msg = v.verify_or_initialize()
            assert ok is False
            assert "FAILED" in msg
            assert "CHANGED" in msg
            assert "CLAUDE.md" in msg

    def test_verify_deleted_file(self, tmp_workspace):
        """Deleted file → return (False, 'FAILED: DELETED')."""
        v = TofuVerifier(str(tmp_workspace))
        stored = v.compute_hashes()

        # Delete CLAUDE.md
        (tmp_workspace / "CLAUDE.md").unlink()

        with patch.object(v, "get_stored_hashes", return_value=stored):
            ok, msg = v.verify_or_initialize()
            assert ok is False
            assert "DELETED" in msg

    def test_verify_new_file(self, tmp_workspace):
        """New file that wasn't there on first run → return (False, 'NEW')."""
        v = TofuVerifier(str(tmp_workspace))

        # Stored hashes had sources.json as None (not present at first run)
        stored = v.compute_hashes()
        stored["sources.json"] = None

        with patch.object(v, "get_stored_hashes", return_value=stored):
            ok, msg = v.verify_or_initialize()
            assert ok is False
            assert "NEW" in msg


class TestConfigMapName:
    """Test ConfigMap name generation."""

    def test_default_name(self, tmp_workspace):
        v = TofuVerifier(str(tmp_workspace))
        assert v.configmap_name == f"tofu-{tmp_workspace.name}"

    def test_custom_name(self, tmp_workspace):
        v = TofuVerifier(str(tmp_workspace), configmap_name="my-tofu-store")
        assert v.configmap_name == "my-tofu-store"
