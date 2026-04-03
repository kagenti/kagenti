# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the parse-env endpoint (parse_env_file function).

Regression tests for issue #1142: displayed variable count must match
the number of rows shown in the UI preview.
"""

import sys
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers import agents


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(agents.router, prefix="/api/v1")
    return application


@pytest.fixture
def client(app):
    with patch("app.routers.agents.require_roles", return_value=lambda: None):
        with TestClient(app) as c:
            yield c


def parse(client, content: str) -> dict:
    resp = client.post("/api/v1/agents/parse-env", json={"content": content})
    assert resp.status_code == 200
    return resp.json()


class TestParseEnvCount:
    """The count of returned envVars must match what users see as rows."""

    def test_seven_var_file(self, client):
        """Regression for #1142: 7-variable .env file returns exactly 7 vars."""
        content = (
            "# Git Issue Agent - Ollama configuration\n"
            "#\n"
            "# Uses a local Ollama instance for LLM inference.\n"
            "\n"
            "# LLM configuration\n"
            "TASK_MODEL_ID=ollama/ibm/granite4:latest\n"
            "# For in-cluster Ollama: LLM_API_BASE=http://ollama.ollama.svc:11434\n"
            "LLM_API_BASE=http://host.docker.internal:11434\n"
            "LLM_API_KEY=ollama\n"
            "MODEL_TEMPERATURE=0\n"
            "\n"
            "# Agent service\n"
            "SERVICE_PORT=8000\n"
            "LOG_LEVEL=DEBUG\n"
            "\n"
            "# MCP Tool endpoint\n"
            "MCP_URL=http://github-tool-mcp:9090/mcp\n"
        )
        result = parse(client, content)
        assert len(result["envVars"]) == 7
        names = [v["name"] for v in result["envVars"]]
        assert names == [
            "TASK_MODEL_ID",
            "LLM_API_BASE",
            "LLM_API_KEY",
            "MODEL_TEMPERATURE",
            "SERVICE_PORT",
            "LOG_LEVEL",
            "MCP_URL",
        ]

    def test_eight_var_file(self, client):
        """8-variable file (with OLLAMA_API_BASE) returns exactly 8 vars."""
        content = (
            "# Git Issue Agent - Ollama configuration\n"
            "TASK_MODEL_ID=ollama_chat/ibm/granite4:latest\n"
            "LLM_API_BASE=http://host.docker.internal:11434\n"
            "OLLAMA_API_BASE=http://host.docker.internal:11434\n"
            "LLM_API_KEY=ollama\n"
            "MODEL_TEMPERATURE=0\n"
            "SERVICE_PORT=8000\n"
            "LOG_LEVEL=DEBUG\n"
            "MCP_URL=http://github-tool-mcp:9090/mcp\n"
        )
        result = parse(client, content)
        assert len(result["envVars"]) == 8

    def test_comments_and_blank_lines_not_counted(self, client):
        """Comments and blank lines must not inflate the variable count."""
        content = "# This is a comment\n\nKEY1=value1\n# another comment\n\nKEY2=value2\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 2

    def test_inline_comment_not_counted_as_extra_var(self, client):
        """Inline comments (KEY=value # note) count as one variable, not two."""
        content = "KEY1=value1 # this is a note\nKEY2=value2\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 2
        # The inline comment must be stripped from the value
        assert result["envVars"][0]["value"] == "value1"

    def test_inline_comment_stripped_from_value(self, client):
        """Value must not include the trailing inline comment."""
        content = "API_BASE=http://host.docker.internal:11434 # local docker\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 1
        assert result["envVars"][0]["value"] == "http://host.docker.internal:11434"

    def test_windows_line_endings(self, client):
        """CRLF line endings must not produce extra variables."""
        content = "KEY1=value1\r\nKEY2=value2\r\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 2

    def test_empty_content(self, client):
        """Empty input returns zero variables."""
        result = parse(client, "")
        assert len(result["envVars"]) == 0

    def test_only_comments_and_blanks(self, client):
        """File with only comments and blank lines returns zero variables."""
        content = "# comment\n\n# another comment\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 0

    def test_commented_out_variable_not_counted(self, client):
        """A commented-out KEY=VALUE line must not be counted as a variable."""
        content = (
            "ACTIVE_KEY=active_value\n# COMMENTED_KEY=commented_value\nANOTHER_KEY=another_value\n"
        )
        result = parse(client, content)
        assert len(result["envVars"]) == 2
        names = [v["name"] for v in result["envVars"]]
        assert "COMMENTED_KEY" not in names

    def test_url_value_with_equals(self, client):
        """URLs with query params (multiple = signs) parse correctly."""
        content = "REDIRECT_URL=https://example.com/callback?code=abc&state=xyz\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 1
        assert result["envVars"][0]["value"] == "https://example.com/callback?code=abc&state=xyz"

    def test_value_from_json(self, client):
        """valueFrom JSON format produces exactly one variable."""
        content = (
            'SECRET_KEY=\'{"valueFrom": {"secretKeyRef": '
            '{"name": "my-secret", "key": "apikey"}}}\'\n'
        )
        result = parse(client, content)
        assert len(result["envVars"]) == 1
        assert "valueFrom" in result["envVars"][0]

    def test_trailing_newline_not_counted(self, client):
        """Trailing newline at end of file does not add an extra variable."""
        content = "KEY1=val1\nKEY2=val2\n"
        result = parse(client, content)
        assert len(result["envVars"]) == 2
