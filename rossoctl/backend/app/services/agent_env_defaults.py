# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Default agent environment variables for UI/TUI import parity."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from app.core.config import settings
from app.core.constants import DEFAULT_IN_CLUSTER_PORT, TOOL_SERVICE_SUFFIX
from app.utils.routes import lookup_service_port

if TYPE_CHECKING:
    from app.routers.agents import CreateAgentRequest, EnvVar
    from app.services.kubernetes import KubernetesService


def get_mcp_tool_url(tool_name: str, namespace: str, kube: "KubernetesService") -> str:
    """Return the in-cluster MCP endpoint URL for a tool (includes /mcp path)."""
    service_name = f"{tool_name}{TOOL_SERVICE_SUFFIX}"
    port = lookup_service_port(service_name, namespace, kube, DEFAULT_IN_CLUSTER_PORT)
    if settings.is_running_in_cluster:
        base = f"http://{service_name}.{namespace}.svc.cluster.local:{port}"
    else:
        base = f"http://{tool_name}.{settings.domain_name}:8080"
    return f"{base}/mcp"


def build_llm_preset_env_vars(
    preset: str,
    model_override: Optional[str] = None,
) -> List["EnvVar"]:
    """Return LLM env vars for a preset (mirrors rossoctl/tui/internal/helpers/helpers.go)."""
    from app.routers.agents import EnvVar, EnvVarSource, SecretKeyRef

    def secret_ref(secret_name: str, key: str) -> EnvVarSource:
        return EnvVarSource(secretKeyRef=SecretKeyRef(name=secret_name, key=key))

    if preset == "openai":
        model = model_override or "gpt-4o-mini-2024-07-18"
        ref = secret_ref("openai-secret", "apikey")
        return [
            EnvVar(name="OPENAI_API_KEY", valueFrom=ref),
            EnvVar(name="LLM_API_KEY", valueFrom=ref),
            EnvVar(name="LLM_API_BASE", value="https://api.openai.com/v1"),
            EnvVar(name="LLM_MODEL", value=model),
        ]
    if preset == "ollama":
        model = model_override or "llama3.2:3b-instruct-fp16"
        return [
            EnvVar(name="LLM_API_BASE", value="http://host.docker.internal:11434/v1"),
            EnvVar(name="LLM_API_KEY", value="dummy"),
            EnvVar(name="LLM_MODEL", value=model),
        ]
    if preset == "openrouter":
        model = model_override or "openai/gpt-4o-mini"
        ref = secret_ref("openai-secret", "apikey")
        return [
            EnvVar(name="OPENAI_API_KEY", valueFrom=ref),
            EnvVar(name="LLM_API_KEY", valueFrom=ref),
            EnvVar(name="LLM_API_BASE", value="https://openrouter.ai/api/v1"),
            EnvVar(name="LLM_MODEL", value=model),
        ]
    return []


def _infer_weather_demo_defaults(
    request: "CreateAgentRequest",
) -> tuple[Optional[str], Optional[str]]:
    """Infer MCP tool + LLM preset for the weather_service example agent."""
    git_path = request.gitPath or ""
    if "weather_service" not in git_path:
        return request.mcpToolName, request.llmPreset

    mcp_tool = request.mcpToolName or "weather-tool"
    llm_preset = request.llmPreset or "openai"
    return mcp_tool, llm_preset


def apply_agent_import_defaults(
    request: "CreateAgentRequest",
    kube: "KubernetesService",
) -> "CreateAgentRequest":
    """Inject MCP_URL and LLM env vars when agent import defaults are enabled."""
    if not settings.rossoctl_feature_flag_agent_import_defaults:
        return request

    mcp_tool, llm_preset = _infer_weather_demo_defaults(request)
    env_vars = list(request.envVars or [])
    existing = {ev.name for ev in env_vars}

    if mcp_tool and "MCP_URL" not in existing:
        from app.routers.agents import EnvVar

        env_vars.append(
            EnvVar(
                name="MCP_URL",
                value=get_mcp_tool_url(mcp_tool, request.namespace, kube),
            )
        )
        existing.add("MCP_URL")

    if llm_preset:
        for ev in build_llm_preset_env_vars(llm_preset, request.llmModel):
            if ev.name not in existing:
                env_vars.append(ev)
                existing.add(ev.name)

    if env_vars == (request.envVars or []):
        return request
    return request.model_copy(
        update={"envVars": env_vars, "mcpToolName": mcp_tool, "llmPreset": llm_preset}
    )
