# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for agent import default env injection."""

from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.routers.agents import CreateAgentRequest, EnvVar
from app.services.agent_env_defaults import (
    apply_agent_import_defaults,
    build_llm_preset_env_vars,
    get_mcp_tool_url,
)


@pytest.fixture(autouse=True)
def enable_import_defaults(monkeypatch):
    monkeypatch.setattr(settings, "kagenti_feature_flag_agent_import_defaults", True)


def test_get_mcp_tool_url_uses_service_port(monkeypatch):
    kube = MagicMock()
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(
        "app.services.agent_env_defaults.lookup_service_port",
        lambda *_args, **_kwargs: 9090,
    )
    url = get_mcp_tool_url("weather-tool", "team1", kube)
    assert url == "http://weather-tool-mcp.team1.svc.cluster.local:9090/mcp"


def test_build_llm_preset_openai():
    envs = build_llm_preset_env_vars("openai")
    names = {ev.name for ev in envs}
    assert names == {"OPENAI_API_KEY", "LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL"}
    base = next(ev for ev in envs if ev.name == "LLM_API_BASE")
    assert base.value == "https://api.openai.com/v1"


def test_apply_defaults_weather_service_git_path(monkeypatch):
    kube = MagicMock()
    monkeypatch.setattr(
        "app.services.agent_env_defaults.get_mcp_tool_url",
        lambda *_a, **_k: "http://weather-tool-mcp.team1.svc.cluster.local:9090/mcp",
    )
    request = CreateAgentRequest(
        name="demo-weather",
        namespace="team1",
        gitPath="a2a/weather_service",
    )
    updated = apply_agent_import_defaults(request, kube)
    env_names = {ev.name for ev in updated.envVars or []}
    assert "MCP_URL" in env_names
    assert "LLM_API_BASE" in env_names
    assert "LLM_MODEL" in env_names
    mcp = next(ev for ev in updated.envVars if ev.name == "MCP_URL")
    assert mcp.value.endswith("/mcp")


def test_apply_defaults_respects_existing_env(monkeypatch):
    kube = MagicMock()
    monkeypatch.setattr(
        "app.services.agent_env_defaults.get_mcp_tool_url",
        lambda *_a, **_k: "http://should-not-be-used/mcp",
    )
    request = CreateAgentRequest(
        name="demo-weather",
        namespace="team1",
        mcpToolName="weather-tool",
        envVars=[EnvVar(name="MCP_URL", value="http://custom/mcp")],
    )
    updated = apply_agent_import_defaults(request, kube)
    mcp = next(ev for ev in updated.envVars if ev.name == "MCP_URL")
    assert mcp.value == "http://custom/mcp"


def test_apply_defaults_disabled(monkeypatch):
    monkeypatch.setattr(settings, "kagenti_feature_flag_agent_import_defaults", False)
    kube = MagicMock()
    request = CreateAgentRequest(
        name="demo-weather",
        namespace="team1",
        gitPath="a2a/weather_service",
    )
    updated = apply_agent_import_defaults(request, kube)
    assert updated.envVars is None
