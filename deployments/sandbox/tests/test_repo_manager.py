"""Tests for repo_manager.py — Multi-repo cloning with access control."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo_manager import RepoManager


class TestIsAllowed:
    """Test URL policy checking."""

    def test_allowed_by_pattern(self, tmp_path, sources_json_path):
        mgr = RepoManager(str(tmp_path), sources_json_path)
        allowed, reason = mgr.is_allowed("https://github.com/kagenti/extensions")
        assert allowed is True
        assert "Allowed" in reason

    def test_denied_by_pattern(self, tmp_path, sources_json_path):
        mgr = RepoManager(str(tmp_path), sources_json_path)
        allowed, reason = mgr.is_allowed("https://github.com/evil-org/malware")
        assert allowed is False
        assert "Denied" in reason

    def test_deny_overrides_allow(self, tmp_path):
        """If a URL matches both allow and deny, deny wins."""
        policy = tmp_path / "policy.json"
        policy.write_text(
            '{"allowed_remotes": ["https://github.com/*"], '
            '"denied_remotes": ["https://github.com/evil-org/*"]}'
        )
        mgr = RepoManager(str(tmp_path), str(policy))
        allowed, _ = mgr.is_allowed("https://github.com/evil-org/sneaky")
        assert allowed is False

    def test_permissive_mode_no_policy(self, tmp_path):
        """No sources.json = allow everything."""
        mgr = RepoManager(str(tmp_path), str(tmp_path / "nonexistent.json"))
        allowed, reason = mgr.is_allowed("https://github.com/anyone/anything")
        assert allowed is True
        assert "permissive" in reason.lower()

    def test_not_in_allowed_list(self, tmp_path, sources_json_path):
        mgr = RepoManager(str(tmp_path), sources_json_path)
        allowed, reason = mgr.is_allowed("https://github.com/random/other")
        assert allowed is False
        assert "Not in allowed_remotes" in reason


class TestClone:
    """Test git clone with policy enforcement."""

    def test_clone_blocked_raises_permission_error(self, tmp_path, sources_json_path):
        mgr = RepoManager(str(tmp_path), sources_json_path)
        with pytest.raises(PermissionError, match="Repo clone blocked"):
            mgr.clone("https://github.com/evil-org/malware")

    def test_clone_max_repos_raises(self, tmp_path, sources_json_path):
        mgr = RepoManager(str(tmp_path), sources_json_path)
        # Simulate 3 already cloned (limit is 3 in fixture)
        mgr._cloned_repos = ["a", "b", "c"]
        with pytest.raises(RuntimeError, match="Max repos limit"):
            mgr.clone("https://github.com/kagenti/another")

    def test_clone_success(self, tmp_path, sources_json_path):
        """Successful clone returns path and records URL."""
        mgr = RepoManager(str(tmp_path), sources_json_path)
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            dest = mgr.clone("https://github.com/kagenti/extensions")
            assert dest == tmp_path / "repos" / "extensions"
            assert "https://github.com/kagenti/extensions" in mgr.list_cloned()

    def test_repo_name_derivation(self, tmp_path, sources_json_path):
        """Strips .git suffix and uses last URL segment."""
        mgr = RepoManager(str(tmp_path), sources_json_path)
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            dest = mgr.clone("https://github.com/kagenti/my-repo.git")
            assert dest.name == "my-repo"

    def test_clone_failure_raises_runtime_error(self, tmp_path, sources_json_path):
        """Git clone failure raises RuntimeError."""
        mgr = RepoManager(str(tmp_path), sources_json_path)
        mock_result = MagicMock(returncode=1, stderr="fatal: repo not found")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="git clone failed"):
                mgr.clone("https://github.com/kagenti/missing")
