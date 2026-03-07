"""Tests for opencode.plugin — A2A wrapper for OpenCode."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from platform_base.permissions import PermissionChecker
from platform_base.sources import SourcesConfig
from platform_base.workspace import WorkspaceManager


class TestGetAgentCard:
    def test_returns_valid_card(self):
        from opencode.plugin import get_agent_card

        card = get_agent_card("localhost", 8000)
        assert card.name == "OpenCode Agent"
        assert card.version == "1.0.0"
        assert card.capabilities.streaming is True
        assert len(card.skills) == 1
        assert card.skills[0].id == "opencode_coding"

    def test_card_url_uses_host_port(self):
        from opencode.plugin import get_agent_card

        card = get_agent_card("10.0.0.1", 9999)
        assert card.url == "http://10.0.0.1:9999/"


class TestBuildExecutor:
    def test_returns_executor_instance(self):
        from opencode.plugin import build_executor

        settings = {"permissions": {"allow": [], "deny": []}}
        sources = {"runtime": {}}
        pc = PermissionChecker(settings)
        sc = SourcesConfig.from_dict(sources)
        wm = WorkspaceManager(
            workspace_root="/tmp/test-oc", agent_name="test", ttl_days=7
        )

        executor = build_executor(
            workspace_manager=wm,
            permission_checker=pc,
            sources_config=sc,
        )
        assert type(executor).__name__ == "OpenCodeExecutor"

    def test_executor_has_workspace_manager(self):
        from opencode.plugin import build_executor

        settings = {"permissions": {"allow": [], "deny": []}}
        sources = {"runtime": {}}
        pc = PermissionChecker(settings)
        sc = SourcesConfig.from_dict(sources)
        wm = WorkspaceManager(
            workspace_root="/tmp/test-oc2", agent_name="test", ttl_days=7
        )

        executor = build_executor(
            workspace_manager=wm,
            permission_checker=pc,
            sources_config=sc,
        )
        assert executor._workspace_manager is wm


class TestOpenCodeProcess:
    def test_initial_state(self):
        from opencode.plugin import OpenCodeProcess

        proc = OpenCodeProcess(port=4096, workspace="/tmp")
        assert proc._started is False
        assert proc.port == 4096

    def test_custom_port(self):
        from opencode.plugin import OpenCodeProcess

        proc = OpenCodeProcess(port=12345)
        assert proc.port == 12345
