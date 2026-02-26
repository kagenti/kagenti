# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox agent deployment API endpoints.

Provides endpoints for deploying new sandbox agents (Deployment + Service)
via the Kubernetes Python client. Mirrors the resources created by
76-deploy-sandbox-agents.sh but driven from the UI wizard.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client import ApiException
from pydantic import BaseModel

from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.routes import create_route_for_agent_or_tool, detect_platform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox-deploy"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SandboxCreateRequest(BaseModel):
    """Request body for creating a new sandbox agent deployment."""

    name: str
    repo: str
    branch: str = "main"
    context_dir: str = "/"
    dockerfile: str = "Dockerfile"
    variant: str = "sandbox-legion"
    model: str = "gpt-4o-mini"
    namespace: str = "team1"
    enable_persistence: bool = True
    isolation_mode: str = "shared"  # shared or pod-per-session
    proxy_allowlist: str = "github.com, api.openai.com, pypi.org"


class SandboxCreateResponse(BaseModel):
    """Response body after initiating a sandbox agent deployment."""

    status: str  # "deploying", "ready", "failed"
    message: str
    agent_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_deployment_manifest(req: SandboxCreateRequest) -> dict:
    """Build a Kubernetes Deployment manifest matching 76-deploy-sandbox-agents.sh.

    The deployment spec mirrors sandbox_legion_deployment.yaml / sandbox_agent_deployment.yaml
    with environment variables for the chosen variant and model.
    """
    namespace = req.namespace
    name = req.name

    # Image from internal registry (same as 76-deploy-sandbox-agents.sh)
    image = f"image-registry.openshift-image-registry.svc:5000/{namespace}/sandbox-agent:v0.0.1"

    # Core env vars shared by all variants
    env_vars = [
        {"name": "PORT", "value": "8000"},
        {"name": "HOST", "value": "0.0.0.0"},
        {"name": "WORKSPACE_ROOT", "value": "/workspace"},
        {
            "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "value": "http://otel-collector.kagenti-system.svc.cluster.local:8335",
        },
        {"name": "LLM_API_BASE", "value": "https://api.openai.com/v1"},
        {
            "name": "LLM_API_KEY",
            "valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}},
        },
        {
            "name": "OPENAI_API_KEY",
            "valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}},
        },
        {"name": "LLM_MODEL", "value": req.model},
        {"name": "UV_CACHE_DIR", "value": "/app/.cache/uv"},
    ]

    # Persistence env vars (PostgreSQL session store + checkpointing)
    if req.enable_persistence:
        db_url = (
            f"postgresql+asyncpg://kagenti:kagenti-sessions-dev"
            f"@postgres-sessions.{namespace}:5432/sessions"
        )
        checkpoint_url = (
            f"postgresql://kagenti:kagenti-sessions-dev"
            f"@postgres-sessions.{namespace}:5432/sessions?sslmode=disable"
        )
        env_vars.append({"name": "TASK_STORE_DB_URL", "value": db_url})
        env_vars.append({"name": "CHECKPOINT_DB_URL", "value": checkpoint_url})

    labels = {
        "kagenti.io/type": "agent",
        "kagenti.io/protocol": "a2a",
        "kagenti.io/framework": "LangGraph",
        "kagenti.io/workload-type": "deployment",
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/managed-by": "kagenti-ui",
        "app.kubernetes.io/component": "agent",
    }

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {
                "kagenti.io/description": f"Sandbox agent ({req.variant}) deployed via UI wizard",
                "kagenti.io/variant": req.variant,
                "kagenti.io/isolation-mode": req.isolation_mode,
                "kagenti.io/proxy-allowlist": req.proxy_allowlist,
                "kagenti.io/source-repo": req.repo,
                "kagenti.io/source-branch": req.branch,
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "kagenti.io/type": "agent",
                    "app.kubernetes.io/name": name,
                },
            },
            "template": {
                "metadata": {
                    "labels": {
                        "kagenti.io/type": "agent",
                        "kagenti.io/protocol": "a2a",
                        "kagenti.io/framework": "LangGraph",
                        "app.kubernetes.io/name": name,
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": "Always",
                            "env": env_vars,
                            "ports": [
                                {
                                    "containerPort": 8000,
                                    "name": "http",
                                    "protocol": "TCP",
                                }
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "256Mi"},
                                "limits": {"cpu": "500m", "memory": "1Gi"},
                            },
                            "volumeMounts": [
                                {"name": "workspace", "mountPath": "/workspace"},
                                {"name": "cache", "mountPath": "/app/.cache"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "workspace", "emptyDir": {"sizeLimit": "5Gi"}},
                        {"name": "cache", "emptyDir": {}},
                    ],
                },
            },
        },
    }


def _build_service_manifest(req: SandboxCreateRequest) -> dict:
    """Build a Kubernetes Service manifest matching sandbox_legion_service.yaml."""
    name = req.name
    namespace = req.namespace

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "kagenti.io/type": "agent",
                "app.kubernetes.io/name": name,
            },
        },
        "spec": {
            "selector": {
                "kagenti.io/type": "agent",
                "app.kubernetes.io/name": name,
            },
            "ports": [
                {
                    "port": 8000,
                    "targetPort": 8000,
                    "protocol": "TCP",
                    "name": "http",
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{namespace}/create", response_model=SandboxCreateResponse)
async def create_sandbox(
    namespace: str,
    request: SandboxCreateRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SandboxCreateResponse:
    """Deploy a new sandbox agent (Deployment + Service) into the given namespace.

    Creates Kubernetes resources matching those produced by
    76-deploy-sandbox-agents.sh. On OpenShift, also creates a Route.
    Returns immediately with status="deploying".
    """
    # Override namespace from the path parameter
    request.namespace = namespace

    deployment_manifest = _build_deployment_manifest(request)
    service_manifest = _build_service_manifest(request)

    # --- Create the Deployment ---
    try:
        kube.create_deployment(namespace=namespace, body=deployment_manifest)
        logger.info(f"Created Deployment '{request.name}' in namespace '{namespace}'")
    except ApiException as e:
        if e.status == 409:
            logger.warning(f"Deployment '{request.name}' already exists in namespace '{namespace}'")
        else:
            logger.error(f"Failed to create Deployment: {e}")
            return SandboxCreateResponse(
                status="failed",
                message=f"Failed to create Deployment: {e.reason}",
            )

    # --- Create the Service ---
    try:
        kube.create_service(namespace=namespace, body=service_manifest)
        logger.info(f"Created Service '{request.name}' in namespace '{namespace}'")
    except ApiException as e:
        if e.status == 409:
            logger.warning(f"Service '{request.name}' already exists in namespace '{namespace}'")
        else:
            logger.error(f"Failed to create Service: {e}")
            return SandboxCreateResponse(
                status="failed",
                message=f"Failed to create Service: {e.reason}",
            )

    # --- Create Route (OpenShift) or skip (Kind/vanilla k8s) ---
    agent_url: Optional[str] = None
    try:
        platform = detect_platform(kube)
        if platform == "openshift":
            create_route_for_agent_or_tool(
                kube=kube,
                name=request.name,
                namespace=namespace,
                service_name=request.name,
                service_port=8000,
            )
            logger.info(f"Created Route for '{request.name}' in namespace '{namespace}'")
        # Build the in-cluster URL regardless of platform
        agent_url = f"http://{request.name}.{namespace}.svc.cluster.local:8000"
    except ApiException as e:
        # Route creation failure is non-fatal — the agent is still accessible in-cluster
        logger.warning(f"Failed to create Route for '{request.name}': {e}")

    return SandboxCreateResponse(
        status="deploying",
        message=f"Sandbox agent '{request.name}' is being deployed in namespace '{namespace}'",
        agent_url=agent_url,
    )
