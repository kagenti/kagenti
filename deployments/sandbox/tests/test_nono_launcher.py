"""Tests for nono_launcher.py — Landlock filesystem sandbox + TOFU integration."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import nono_launcher
from nono_launcher import apply_sandbox, main, verify_tofu


class TestApplySandbox:
    """Test Landlock sandbox application."""

    def test_returns_false_without_nono_py(self):
        """When nono_py is not installed, return False and warn."""
        with patch.dict(sys.modules, {"nono_py": None}):
            importlib.reload(nono_launcher)
            result = nono_launcher.apply_sandbox()
            assert result is False

    def test_returns_true_with_nono_py(self):
        """When nono_py is available, apply sandbox and return True."""
        mock_nono = MagicMock()
        mock_caps = MagicMock()
        mock_nono.CapabilitySet.return_value = mock_caps
        mock_nono.AccessMode.READ = "READ"
        mock_nono.AccessMode.READ_WRITE = "READ_WRITE"

        with patch.dict(sys.modules, {"nono_py": mock_nono}):
            importlib.reload(nono_launcher)
            result = nono_launcher.apply_sandbox()
            assert result is True
            mock_nono.apply.assert_called_once_with(mock_caps)

    def test_workspace_env_override(self):
        """WORKSPACE_DIR env var overrides default /workspace."""
        mock_nono = MagicMock()
        mock_caps = MagicMock()
        mock_nono.CapabilitySet.return_value = mock_caps
        mock_nono.AccessMode.READ = "READ"
        mock_nono.AccessMode.READ_WRITE = "READ_WRITE"

        with patch.dict(sys.modules, {"nono_py": mock_nono}):
            with patch.dict(os.environ, {"WORKSPACE_DIR": "/custom/ws"}):
                with patch("os.path.exists", return_value=True):
                    importlib.reload(nono_launcher)
                    nono_launcher.apply_sandbox()
                    calls = mock_caps.allow_path.call_args_list
                    rw_paths = [c[0][0] for c in calls if c[0][1] == "READ_WRITE"]
                    assert "/custom/ws" in rw_paths


class TestVerifyTofu:
    """Test TOFU verification integration."""

    def test_tofu_success(self, tmp_workspace):
        """TOFU passes when hashes match."""
        mock_verifier = MagicMock()
        mock_verifier.verify_or_initialize.return_value = (True, "verified: 2 files")
        mock_tofu = MagicMock()
        mock_tofu.TofuVerifier.return_value = mock_verifier

        with patch.dict(os.environ, {"WORKSPACE_DIR": str(tmp_workspace)}):
            with patch.dict(sys.modules, {"tofu": mock_tofu}):
                importlib.reload(nono_launcher)
                ok, msg = nono_launcher.verify_tofu()
                assert ok is True
                assert "verified" in msg

    def test_tofu_failure(self, tmp_workspace):
        """TOFU fails when hashes mismatch."""
        mock_verifier = MagicMock()
        mock_verifier.verify_or_initialize.return_value = (
            False,
            "FAILED: CLAUDE.md CHANGED",
        )
        mock_tofu = MagicMock()
        mock_tofu.TofuVerifier.return_value = mock_verifier

        with patch.dict(os.environ, {"WORKSPACE_DIR": str(tmp_workspace)}):
            with patch.dict(sys.modules, {"tofu": mock_tofu}):
                importlib.reload(nono_launcher)
                ok, msg = nono_launcher.verify_tofu()
                assert ok is False
                assert "FAILED" in msg

    def test_tofu_module_missing(self):
        """When tofu module is not importable, return True (skip)."""
        with patch.dict(sys.modules, {"tofu": None}):
            importlib.reload(nono_launcher)
            ok, msg = nono_launcher.verify_tofu()
            assert ok is True
            assert "skipped" in msg


class TestMain:
    """Test main() entry point."""

    def test_main_with_command(self):
        """With args, execvp is called with those args."""
        with patch("nono_launcher.verify_tofu", return_value=(True, "ok")):
            with patch("nono_launcher.apply_sandbox", return_value=True):
                with patch("os.execvp") as mock_exec:
                    with patch.object(
                        sys,
                        "argv",
                        ["nono_launcher.py", "python3", "agent_server.py"],
                    ):
                        main()
                        mock_exec.assert_called_once_with(
                            "python3", ["python3", "agent_server.py"]
                        )

    def test_main_without_command(self):
        """Without args, execvp uses default sleep command."""
        with patch("nono_launcher.verify_tofu", return_value=(True, "ok")):
            with patch("nono_launcher.apply_sandbox", return_value=False):
                with patch("os.execvp") as mock_exec:
                    with patch.object(sys, "argv", ["nono_launcher.py"]):
                        main()
                        mock_exec.assert_called_once()
                        assert mock_exec.call_args[0][0] == "/bin/sh"

    def test_main_tofu_fail_no_enforce(self):
        """TOFU failure without TOFU_ENFORCE continues."""
        with patch("nono_launcher.verify_tofu", return_value=(False, "FAILED")):
            with patch("nono_launcher.apply_sandbox", return_value=False):
                with patch("os.execvp") as mock_exec:
                    with patch.object(sys, "argv", ["nono_launcher.py", "echo"]):
                        env = os.environ.copy()
                        env.pop("TOFU_ENFORCE", None)
                        with patch.dict(os.environ, env, clear=True):
                            main()
                            mock_exec.assert_called_once()

    def test_main_tofu_fail_with_enforce(self):
        """TOFU failure with TOFU_ENFORCE=true exits."""
        with patch("nono_launcher.verify_tofu", return_value=(False, "FAILED")):
            with patch.dict(os.environ, {"TOFU_ENFORCE": "true"}):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
