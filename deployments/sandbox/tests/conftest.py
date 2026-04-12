"""Shared fixtures for sandbox module tests."""

import os
import sys
from pathlib import Path

import pytest

# Add deployments/sandbox to path so modules can be imported
SANDBOX_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SANDBOX_DIR))


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with sample files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create CLAUDE.md
    (workspace / "CLAUDE.md").write_text("# Test Project\n\nSome instructions.\n")

    # Create .claude/settings.json
    claude_dir = workspace / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text('{"key": "value"}\n')

    # Create sources.json
    (workspace / "sources.json").write_text(
        '{"allowed_remotes": ["https://github.com/kagenti/*"], '
        '"denied_remotes": ["https://github.com/evil-org/*"], '
        '"resource_limits": {"max_repos": 3}}\n'
    )

    return workspace


@pytest.fixture
def sources_json_path(tmp_workspace):
    """Path to the sources.json in the temp workspace."""
    return str(tmp_workspace / "sources.json")
