"""Tests for skill_pack_loader.py — Versioned skill packs for sandbox agents.

TDD: these tests define the expected behavior of SkillPackLoader before
it is implemented.
"""

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from skill_pack_loader import SkillPackLoader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MANIFEST = {
    "version": 1,
    "trusted_keys": [
        {"id": "anthropic-bot", "fingerprint": "SHA256:placeholder", "type": "gpg"},
    ],
    "packs": [
        {
            "name": "superpowers",
            "description": "Claude Code superpowers",
            "source": "https://github.com/claude-plugins-official/superpowers",
            "commit": "abc123",
            "path": "skills/",
            "integrity": "sha256:deadbeef",
            "signer": "anthropic-bot",
            "default": True,
        },
        {
            "name": "debugging",
            "description": "Advanced debugging skills",
            "source": "https://github.com/example/debugging",
            "commit": "def456",
            "path": "skills/",
            "integrity": "sha256:cafebabe",
            "signer": "anthropic-bot",
            "default": False,
        },
    ],
}


@pytest.fixture
def manifest_path(tmp_path):
    """Write a sample skill-packs.yaml and return its path."""
    config = tmp_path / "skill-packs.yaml"
    config.write_text(yaml.dump(SAMPLE_MANIFEST, default_flow_style=False))
    return str(config)


@pytest.fixture
def workspace(tmp_path):
    """Create and return a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


# ---------------------------------------------------------------------------
# 1. Manifest loading
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_load_manifest(self, manifest_path, workspace):
        """SkillPackLoader reads skill-packs.yaml and exposes packs."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        assert loader.manifest["version"] == 1
        assert len(loader.manifest["packs"]) == 2
        assert loader.manifest["packs"][0]["name"] == "superpowers"

    def test_load_manifest_missing_file(self, workspace):
        """Raises FileNotFoundError if manifest does not exist."""
        with pytest.raises(FileNotFoundError):
            SkillPackLoader(
                config_path="/nonexistent/skill-packs.yaml", workspace=workspace
            )


# ---------------------------------------------------------------------------
# 2. Pack filtering
# ---------------------------------------------------------------------------


class TestFilterPacks:
    def test_filter_default_packs(self, manifest_path, workspace):
        """get_default_packs returns only packs with default: true."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        defaults = loader.get_default_packs()
        assert len(defaults) == 1
        assert defaults[0]["name"] == "superpowers"

    def test_filter_selected_packs(self, manifest_path, workspace):
        """get_packs returns packs matching the given names."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        selected = loader.get_packs(["debugging"])
        assert len(selected) == 1
        assert selected[0]["name"] == "debugging"

    def test_filter_unknown_pack_skipped(self, manifest_path, workspace):
        """get_packs silently skips names that don't match any pack."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        selected = loader.get_packs(["nonexistent", "debugging"])
        assert len(selected) == 1
        assert selected[0]["name"] == "debugging"


# ---------------------------------------------------------------------------
# 3. Content hashing
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_compute_content_hash(self, tmp_path):
        """compute_content_hash returns sha256:<hex> of directory contents."""
        d = tmp_path / "skills"
        d.mkdir()
        (d / "a.md").write_text("alpha")
        (d / "b.md").write_text("bravo")

        loader = SkillPackLoader.__new__(SkillPackLoader)
        result = loader.compute_content_hash(str(d))
        assert result.startswith("sha256:")
        assert len(result.split(":")[1]) == 64  # hex SHA-256

    def test_content_hash_deterministic(self, tmp_path):
        """Same files produce the same hash regardless of call order."""
        d = tmp_path / "skills"
        d.mkdir()
        (d / "z.md").write_text("zulu")
        (d / "a.md").write_text("alpha")

        loader = SkillPackLoader.__new__(SkillPackLoader)
        h1 = loader.compute_content_hash(str(d))
        h2 = loader.compute_content_hash(str(d))
        assert h1 == h2


# ---------------------------------------------------------------------------
# 4. Git operations (mocked)
# ---------------------------------------------------------------------------


class TestGitOperations:
    def test_clone_at_commit(self, tmp_path, manifest_path, workspace):
        """clone_pack runs git clone --no-checkout then git checkout <commit>."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        pack = SAMPLE_MANIFEST["packs"][0]
        target = str(tmp_path / "clone-target")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            loader.clone_pack(pack, target)

        # First call: git clone --no-checkout
        clone_call = mock_run.call_args_list[0]
        clone_cmd = clone_call[0][0]
        assert "clone" in clone_cmd
        assert "--no-checkout" in clone_cmd
        assert pack["source"] in clone_cmd

        # Second call: git checkout <commit>
        checkout_call = mock_run.call_args_list[1]
        checkout_cmd = checkout_call[0][0]
        assert "checkout" in checkout_cmd
        assert pack["commit"] in checkout_cmd

    def test_verify_commit_signature_good(self, manifest_path, workspace, tmp_path):
        """verify_commit_signature returns True for a good GPG signature."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        repo_path = str(tmp_path / "repo")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Good signature from anthropic-bot",
                stderr="",
            )
            result = loader.verify_commit_signature(
                repo_path, "abc123", "anthropic-bot"
            )

        assert result is True

    def test_verify_commit_signature_fails(self, manifest_path, workspace, tmp_path):
        """verify_commit_signature returns False for a bad/missing signature."""
        loader = SkillPackLoader(config_path=manifest_path, workspace=workspace)
        repo_path = str(tmp_path / "repo")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error: no signature found",
            )
            result = loader.verify_commit_signature(
                repo_path, "abc123", "anthropic-bot"
            )

        assert result is False


# ---------------------------------------------------------------------------
# 5. Skill installation
# ---------------------------------------------------------------------------


class TestInstallSkills:
    def test_install_skills_to_workspace(self, tmp_path):
        """install_pack copies skill files into /workspace/.claude/skills/<name>/."""
        ws = tmp_path / "workspace"
        ws.mkdir()

        # Create source skill directory with a SKILL.md file
        source_dir = tmp_path / "source" / "skills" / "my-skill"
        source_dir.mkdir(parents=True)
        (source_dir / "SKILL.md").write_text("# My Skill\nSome content.")
        (source_dir / "helper.py").write_text("def help(): pass")

        loader = SkillPackLoader.__new__(SkillPackLoader)
        loader.workspace = str(ws)

        loader.install_pack(str(tmp_path / "source" / "skills"), "superpowers")

        installed = Path(ws) / ".claude" / "skills" / "superpowers"
        assert installed.is_dir()
        # The files from the source should be present under the pack name
        assert (installed / "my-skill" / "SKILL.md").exists()
        assert (installed / "my-skill" / "helper.py").exists()
