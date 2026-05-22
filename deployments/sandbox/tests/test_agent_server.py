"""Tests for agent_server.py — repo_manager integration."""

import json
import os
from http.server import HTTPServer
from threading import Thread
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

import pytest

from agent_server import AgentHandler, main


@pytest.fixture
def server(tmp_workspace):
    """Start a test server on a random port."""
    from skills_loader import SkillsLoader
    from repo_manager import RepoManager

    loader = SkillsLoader(str(tmp_workspace))
    AgentHandler.loader = loader
    AgentHandler.model = "test-model"
    AgentHandler.repo_manager = RepoManager(
        str(tmp_workspace), str(tmp_workspace / "sources.json")
    )

    httpd = HTTPServer(("127.0.0.1", 0), AgentHandler)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


class TestHealthEndpoint:
    def test_health(self, server):
        resp = urlopen(f"{server}/health")
        data = json.loads(resp.read())
        assert data["status"] == "ok"


class TestInfoEndpoint:
    def test_info_includes_repos(self, server):
        resp = urlopen(f"{server}/info")
        data = json.loads(resp.read())
        assert "repos" in data
        assert isinstance(data["repos"], list)

    def test_info_includes_model(self, server):
        resp = urlopen(f"{server}/info")
        data = json.loads(resp.read())
        assert data["model"] == "test-model"


class TestReposEndpoint:
    def test_repos_endpoint(self, server):
        resp = urlopen(f"{server}/repos")
        data = json.loads(resp.read())
        assert "cloned" in data
        assert "on_disk" in data

    def test_repos_without_manager(self, server):
        """Without repo_manager, returns 503."""
        AgentHandler.repo_manager = None
        try:
            urlopen(f"{server}/repos")
            assert False, "Should have raised"
        except Exception as e:
            assert "503" in str(e) or "HTTP Error" in str(e)
