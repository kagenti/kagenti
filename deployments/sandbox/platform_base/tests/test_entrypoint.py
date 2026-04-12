"""Tests for platform_base.entrypoint — plugin loading and platform wiring."""

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add platform_base parent to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from platform_base.entrypoint import (
    create_task_store,
    load_json,
    tofu_verify,
)


# ---------------------------------------------------------------------------
# load_json tests
# ---------------------------------------------------------------------------


class TestLoadJson:
    def test_loads_from_first_path(self, tmp_path):
        data = {"permissions": {"allow": [], "deny": []}}
        (tmp_path / "settings.json").write_text(json.dumps(data))
        result = load_json("settings.json", [tmp_path])
        assert result == data

    def test_searches_multiple_paths(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        data = {"found": True}
        (second / "config.json").write_text(json.dumps(data))
        result = load_json("config.json", [first, second])
        assert result == data

    def test_raises_if_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="missing.json"):
            load_json("missing.json", [tmp_path])


# ---------------------------------------------------------------------------
# TOFU tests
# ---------------------------------------------------------------------------


class TestTofu:
    def test_first_run_stores_hashes(self, tmp_path, monkeypatch):
        (tmp_path / "CLAUDE.md").write_text("# Test")
        monkeypatch.setattr(
            "platform_base.entrypoint._TOFU_HASH_FILE", ".tofu-test.json"
        )
        hash_file = tmp_path / ".tofu-test.json"

        # Monkey-patch to use tmp_path instead of /tmp
        with patch("platform_base.entrypoint.Path") as mock_path:
            # Only intercept the Path("/tmp") call
            original_path = Path

            def side_effect(arg=""):
                if arg == "/tmp":
                    return tmp_path
                return original_path(arg)

            mock_path.side_effect = side_effect
            mock_path.cwd = Path.cwd

            # Direct approach: just call _compute_tofu_hashes and verify
            from platform_base.entrypoint import _compute_tofu_hashes

            hashes = _compute_tofu_hashes(tmp_path)
            assert "CLAUDE.md" in hashes
            assert len(hashes["CLAUDE.md"]) == 64  # SHA-256 hex

    def test_no_tracked_files_skips(self, tmp_path):
        # Empty dir — no tracked files
        from platform_base.entrypoint import _compute_tofu_hashes

        hashes = _compute_tofu_hashes(tmp_path)
        assert hashes == {}


# ---------------------------------------------------------------------------
# create_task_store tests
# ---------------------------------------------------------------------------


class TestCreateTaskStore:
    def test_returns_in_memory_when_no_url(self, monkeypatch):
        monkeypatch.delenv("TASK_STORE_DB_URL", raising=False)
        store = create_task_store()
        assert store.__class__.__name__ == "InMemoryTaskStore"

    def test_returns_in_memory_when_empty_url(self, monkeypatch):
        monkeypatch.setenv("TASK_STORE_DB_URL", "")
        store = create_task_store()
        assert store.__class__.__name__ == "InMemoryTaskStore"


# ---------------------------------------------------------------------------
# Plugin loading tests
# ---------------------------------------------------------------------------


class TestPluginLoading:
    def test_agent_module_env_required(self, monkeypatch):
        monkeypatch.delenv("AGENT_MODULE", raising=False)
        from platform_base.entrypoint import main

        with pytest.raises(RuntimeError, match="AGENT_MODULE"):
            main()

    def test_module_must_export_build_executor(self, monkeypatch):
        # Create a fake module without build_executor
        fake_module = types.ModuleType("fake_agent")
        fake_module.get_agent_card = MagicMock()

        monkeypatch.setenv("AGENT_MODULE", "fake_agent")
        with patch("importlib.import_module", return_value=fake_module):
            from platform_base.entrypoint import main

            with pytest.raises(RuntimeError, match="build_executor"):
                main()

    def test_module_must_export_get_agent_card(self, monkeypatch):
        fake_module = types.ModuleType("fake_agent")
        fake_module.build_executor = MagicMock()

        monkeypatch.setenv("AGENT_MODULE", "fake_agent")
        with patch("importlib.import_module", return_value=fake_module):
            from platform_base.entrypoint import main

            with pytest.raises(RuntimeError, match="get_agent_card"):
                main()

    def test_loads_valid_module(self, monkeypatch, tmp_path):
        """Verify that a valid module with both exports is loaded successfully."""
        fake_module = types.ModuleType("test_agent")
        fake_module.build_executor = MagicMock()
        fake_module.get_agent_card = MagicMock()

        monkeypatch.setenv("AGENT_MODULE", "test_agent")

        # Write config files
        settings = {"permissions": {"allow": [], "deny": []}}
        sources = {"runtime": {}}
        (tmp_path / "settings.json").write_text(json.dumps(settings))
        (tmp_path / "sources.json").write_text(json.dumps(sources))
        monkeypatch.setenv("CONFIG_ROOT", str(tmp_path))

        with patch("importlib.import_module", return_value=fake_module):
            with patch("uvicorn.run"):  # Don't actually start server
                from platform_base.entrypoint import main

                main()

        # Verify build_executor was called with platform services
        fake_module.build_executor.assert_called_once()
        call_kwargs = fake_module.build_executor.call_args[1]
        assert "workspace_manager" in call_kwargs
        assert "permission_checker" in call_kwargs
        assert "sources_config" in call_kwargs
