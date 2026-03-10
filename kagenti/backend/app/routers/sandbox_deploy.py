# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox agent deployment API endpoints.

Provides endpoints for deploying new sandbox agents (Deployment + Service)
via the Kubernetes Python client. Mirrors the resources created by
76-deploy-sandbox-agents.sh but driven from the UI wizard.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from kubernetes.client import ApiException
from pydantic import BaseModel

from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.routes import create_route_for_agent_or_tool, detect_platform

# Add deployments/sandbox to path for SandboxProfile
# Walk up to find repo root (works at any depth, including containers)
_this_dir = Path(__file__).resolve().parent
_sandbox_dir = None
for _parent in _this_dir.parents:
    _candidate = _parent / "deployments" / "sandbox"
    if _candidate.is_dir():
        _sandbox_dir = _candidate
        break
if _sandbox_dir and str(_sandbox_dir) not in sys.path:
    sys.path.insert(0, str(_sandbox_dir))

try:
    from sandbox_profile import SandboxProfile  # noqa: E402  # pylint: disable=wrong-import-position,wrong-import-order
except ImportError:
    SandboxProfile = None

logger = logging.getLogger(__name__)

# Cluster-aware LLM defaults — set via env vars on the backend deployment
# or via Helm values. Route through LiteLLM proxy for proper tool calling
# support across all models (Llama 4, Mistral, GPT, etc.).
DEFAULT_LLM_API_BASE = os.environ.get(
    "SANDBOX_LLM_API_BASE",
    "http://litellm-proxy.kagenti-system.svc.cluster.local:4000/v1",
)
DEFAULT_LLM_MODEL = os.environ.get("SANDBOX_LLM_MODEL", "llama-4-scout")
DEFAULT_LLM_SECRET = os.environ.get("SANDBOX_LLM_SECRET", "litellm-proxy-secret")

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
    base_agent: str = "sandbox-legion"
    model: str = ""  # Empty = use cluster default (DEFAULT_LLM_MODEL)
    namespace: str = "team1"
    enable_persistence: bool = True
    isolation_mode: str = "shared"  # shared or pod-per-session
    workspace_size: str = "5Gi"
    workspace_storage: str = "emptydir"  # "emptydir" or "pvc"
    # Composable security layers (Session F)
    secctx: bool = True
    landlock: bool = False
    proxy: bool = False
    gvisor: bool = False
    proxy_domains: Optional[str] = None
    # Deployment mechanism
    managed_lifecycle: bool = False
    ttl_hours: int = 2
    # Legacy fields (kept for backwards compat)
    non_root: bool = True
    drop_caps: bool = True
    read_only_root: bool = False
    proxy_allowlist: str = "github.com, pypi.org"
    # Credentials
    github_pat: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_key_source: str = "existing"  # "existing" or "new"
    llm_secret_name: str = ""  # Empty = use cluster default (DEFAULT_LLM_SECRET)
    # Skill packs (Session M)
    skill_packs: list[str] = []  # Pack names from skill-packs.yaml (empty = defaults)

    @property
    def profile(self):
        """Build a SandboxProfile from this request's security toggles."""
        if SandboxProfile is None:
            return None
        return SandboxProfile(
            base_agent=self.base_agent,
            secctx=self.secctx,
            landlock=self.landlock,
            proxy=self.proxy,
            gvisor=self.gvisor,
            managed_lifecycle=self.managed_lifecycle,
            ttl_hours=self.ttl_hours,
            namespace=self.namespace,
            proxy_domains=self.proxy_domains,
        )

    @property
    def composable_name(self) -> str:
        """Self-documenting agent name from active layers."""
        return self.profile.name


class SandboxCreateResponse(BaseModel):
    """Response body after initiating a sandbox agent deployment."""

    status: str  # "deploying", "ready", "failed"
    message: str
    agent_url: Optional[str] = None
    composable_name: Optional[str] = None
    security_warnings: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_squid_conf(req: SandboxCreateRequest) -> str:
    """Build squid.conf content from the request's proxy domain list.

    When domains are specified, only those are allowed.
    When empty, all egress is denied (secure default).

    Config is designed for non-root containers (OCP arbitrary UID):
    all writable paths point to /tmp.
    """
    proxy_domains = req.proxy_domains or req.proxy_allowlist or ""
    domain_lines = ""
    for domain in proxy_domains.split(","):
        d = domain.strip()
        if d:
            domain_lines += f"acl allowed_domains dstdomain .{d}\n"

    base = (
        "http_port 3128\n"
        "pid_filename /tmp/squid.pid\n"
        "cache_log /tmp/cache.log\n"
        "access_log /tmp/access.log\n"
        "coredump_dir /tmp\n"
        "cache_dir null /tmp\n"
        "cache deny all\n"
        "logfile_rotate 0\n"
        "acl localnet src 10.0.0.0/8\n"
        "acl localnet src 172.16.0.0/12\n"
        "acl localnet src 192.168.0.0/16\n"
        "acl localnet src 127.0.0.0/8\n"
        "acl SSL_ports port 443\n"
        "acl Safe_ports port 80\n"
        "acl Safe_ports port 443\n"
        "acl Safe_ports port 8000-9000\n"
        "acl CONNECT method CONNECT\n"
        "http_access deny !Safe_ports\n"
        "http_access deny CONNECT !SSL_ports\n"
    )
    if domain_lines:
        return (
            base
            + domain_lines
            + "http_access allow localnet allowed_domains\nhttp_access deny all\n"
        )
    return base + "http_access deny all\n"


def _build_deployment_manifest(
    req: SandboxCreateRequest,
    llm_secret: Optional[str] = None,
    github_pat_secret: Optional[str] = None,
) -> dict:
    """Build a Kubernetes Deployment manifest matching 76-deploy-sandbox-agents.sh.

    The deployment spec mirrors sandbox_legion_deployment.yaml / sandbox_agent_deployment.yaml
    with environment variables for the chosen variant and model.

    Args:
        req: The sandbox create request.
        llm_secret: Name of the K8s Secret containing the LLM API key (key: "apikey").
        github_pat_secret: Name of the K8s Secret containing the GitHub PAT (key: "token").
                           If None, no GITHUB_TOKEN env var is injected.
    """
    namespace = req.namespace
    name = req.name

    # Image from internal registry (same as 76-deploy-sandbox-agents.sh)
    image = f"image-registry.openshift-image-registry.svc:5000/{namespace}/sandbox-agent:v0.0.1"

    # Resolve cluster-aware defaults
    effective_secret = llm_secret or req.llm_secret_name or DEFAULT_LLM_SECRET
    effective_model = req.model or DEFAULT_LLM_MODEL
    effective_api_base = DEFAULT_LLM_API_BASE

    # Core env vars shared by all variants
    env_vars = [
        {"name": "PORT", "value": "8000"},
        {"name": "HOST", "value": "0.0.0.0"},
        {"name": "WORKSPACE_ROOT", "value": "/workspace"},
        {
            "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "value": "http://otel-collector.kagenti-system.svc.cluster.local:8335",
        },
        {"name": "LLM_API_BASE", "value": effective_api_base},
        {
            "name": "LLM_API_KEY",
            "valueFrom": {"secretKeyRef": {"name": effective_secret, "key": "apikey"}},
        },
        {
            "name": "OPENAI_API_KEY",
            "valueFrom": {"secretKeyRef": {"name": effective_secret, "key": "apikey"}},
        },
        {"name": "LLM_MODEL", "value": effective_model},
        {"name": "UV_CACHE_DIR", "value": "/app/.cache/uv"},
    ]

    # Inject GitHub PAT for gh CLI and git operations.
    # GH_TOKEN is read by the gh CLI; GITHUB_TOKEN by git credential helpers.
    gh_secret = github_pat_secret or "github-token-secret"
    for env_name in ("GH_TOKEN", "GITHUB_TOKEN"):
        env_vars.append(
            {
                "name": env_name,
                "valueFrom": {"secretKeyRef": {"name": gh_secret, "key": "token"}},
            }
        )

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

    # -- Container security context from wizard settings --
    security_context: dict = {}
    if req.non_root:
        security_context["runAsNonRoot"] = True
    if req.drop_caps:
        security_context["allowPrivilegeEscalation"] = False
        security_context["capabilities"] = {"drop": ["ALL"]}
    security_context["seccompProfile"] = {"type": "RuntimeDefault"}
    # readOnlyRootFilesystem only if explicitly requested AND not postgres-dependent
    if req.read_only_root:
        security_context["readOnlyRootFilesystem"] = True

    init_containers: list[dict] = []

    # Workspace volume: "pvc" for persistence, "emptydir" for ephemeral.
    # No fallback — deploy exactly what was selected or fail.
    workspace_pvc_name = f"{name}-workspace"
    if req.workspace_storage == "pvc":
        workspace_vol = {
            "name": "workspace",
            "persistentVolumeClaim": {"claimName": workspace_pvc_name},
        }
    else:
        workspace_vol = {"name": "workspace", "emptyDir": {"sizeLimit": req.workspace_size}}
    volumes = [workspace_vol, {"name": "cache", "emptyDir": {}}]

    # -- Per-agent egress proxy (separate pod) -----------------------------
    # Each agent gets its own egress-proxy Deployment + Service with a
    # ConfigMap containing the domain allowlist from the wizard.
    # The agent's HTTP_PROXY env var points to the proxy service.
    # A namespace-wide NetworkPolicy blocks direct public egress from
    # agent pods — only the egress-proxy pods can reach the internet.
    proxy_svc = f"{name}-egress-proxy"
    proxy_url = f"http://{proxy_svc}.{namespace}.svc:3128"
    no_proxy = "localhost,127.0.0.1,.svc,.svc.cluster.local"
    for var_name in ("HTTP_PROXY", "http_proxy"):
        env_vars.append({"name": var_name, "value": proxy_url})
    for var_name in ("HTTPS_PROXY", "https_proxy"):
        env_vars.append({"name": var_name, "value": proxy_url})
    for var_name in ("NO_PROXY", "no_proxy"):
        env_vars.append({"name": var_name, "value": no_proxy})

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {
                "kagenti.io/description": f"Sandbox agent ({req.base_agent}) deployed via UI wizard",
                "kagenti.io/variant": req.base_agent,
                "kagenti.io/isolation-mode": req.isolation_mode,
                "kagenti.io/proxy-allowlist": req.proxy_allowlist,
                "kagenti.io/source-repo": req.repo,
                "kagenti.io/source-branch": req.branch,
            },
        },
        "spec": {
            "replicas": 1,
            # Recreate strategy: old pod stops before new starts.
            # Required for RWO PVC — can't mount on two pods simultaneously.
            "strategy": {"type": "Recreate"},
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
                    "initContainers": init_containers,
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
                            "securityContext": security_context,
                            "volumeMounts": [
                                {"name": "workspace", "mountPath": "/workspace"},
                                {"name": "cache", "mountPath": "/app/.cache"},
                            ],
                        },
                    ],
                    "volumes": volumes,
                },
            },
        },
    }


def _build_egress_proxy_manifests(req: SandboxCreateRequest) -> tuple[dict, dict]:
    """Build Deployment + Service manifests for the per-agent egress proxy.

    Returns (deployment, service) dicts.
    """
    name = f"{req.name}-egress-proxy"
    namespace = req.namespace
    labels = {
        "kagenti.io/type": "egress-proxy",
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/part-of": req.name,
        "app.kubernetes.io/managed-by": "kagenti-ui",
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [
                        {
                            "name": "squid",
                            "image": "ubuntu/squid:latest",
                            "command": [
                                "squid",
                                "--foreground",
                                "-f",
                                "/etc/squid/squid.conf",
                                "-YC",
                            ],
                            "ports": [{"containerPort": 3128}],
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "64Mi"},
                                "limits": {"cpu": "200m", "memory": "256Mi"},
                            },
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/etc/squid/squid.conf",
                                    "subPath": "squid.conf",
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "configMap": {"name": f"{req.name}-squid-config"},
                        }
                    ],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "selector": {"app.kubernetes.io/name": name},
            "ports": [{"port": 3128, "targetPort": 3128, "protocol": "TCP"}],
        },
    }
    return deployment, service


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

    # --- Composable security profile (Session F) ---
    profile = request.profile
    composable_name = profile.name if profile else request.name
    security_warnings = profile.warnings if profile else []
    if security_warnings:
        logger.warning(
            "Security warnings for '%s': %s",
            composable_name,
            "; ".join(security_warnings),
        )

    # --- Create credential Secrets when the user provides new values ---
    managed_labels = {
        "app.kubernetes.io/managed-by": "kagenti-ui",
        "app.kubernetes.io/part-of": request.name,
    }

    # LLM API key secret
    if request.llm_key_source == "new" and request.llm_api_key:
        llm_secret = f"{request.name}-llm-secret"
        try:
            kube.create_secret(
                namespace=namespace,
                name=llm_secret,
                string_data={"apikey": request.llm_api_key},
                labels=managed_labels,
            )
            logger.info(f"Created LLM API key Secret '{llm_secret}' in namespace '{namespace}'")
        except ApiException as e:
            logger.error(f"Failed to create LLM Secret: {e}")
            return SandboxCreateResponse(
                status="failed",
                message=f"Failed to create LLM API key Secret: {e.reason}",
            )
    else:
        llm_secret = request.llm_secret_name

    # GitHub PAT secret
    github_pat_secret: Optional[str] = None
    if request.github_pat:
        github_pat_secret = f"{request.name}-github-pat"
        try:
            kube.create_secret(
                namespace=namespace,
                name=github_pat_secret,
                string_data={"token": request.github_pat},
                labels=managed_labels,
            )
            logger.info(
                f"Created GitHub PAT Secret '{github_pat_secret}' in namespace '{namespace}'"
            )
        except ApiException as e:
            logger.error(f"Failed to create GitHub PAT Secret: {e}")
            return SandboxCreateResponse(
                status="failed",
                message=f"Failed to create GitHub PAT Secret: {e.reason}",
            )

    deployment_manifest = _build_deployment_manifest(
        request,
        llm_secret=llm_secret,
        github_pat_secret=github_pat_secret,
    )
    service_manifest = _build_service_manifest(request)

    # --- Create skill-pack ConfigMaps (init container dependencies) ---
    managed_cm_labels = {
        "app.kubernetes.io/managed-by": "kagenti-ui",
        "app.kubernetes.io/part-of": request.name,
    }

    # Skills are loaded by the agent at startup (git clone from sources.json).
    # No ConfigMaps or init containers needed — the agent handles skill loading.
    # TODO(Session N): Once base image moves to kagenti repo, bake
    # skill_pack_loader.py into the image for verified skill loading.

    # --- Create workspace PVC if selected (no fallback — fail if it can't be created) ---
    if request.workspace_storage == "pvc":
        workspace_pvc_name = f"{request.name}-workspace"
        try:
            pvc_body = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {
                    "name": workspace_pvc_name,
                    "namespace": namespace,
                    "labels": managed_cm_labels,
                },
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {
                        "requests": {"storage": request.workspace_size},
                    },
                },
            }
            kube.core_api.create_namespaced_persistent_volume_claim(
                namespace=namespace, body=pvc_body
            )
            logger.info(
                "Created workspace PVC '%s' (%s)",
                workspace_pvc_name,
                request.workspace_size,
            )
        except ApiException as e:
            if e.status == 409:
                logger.info("Workspace PVC '%s' already exists", workspace_pvc_name)
            else:
                logger.error("Failed to create workspace PVC: %s", e)
                return SandboxCreateResponse(
                    status="failed",
                    message=f"Failed to create workspace PVC: {e.reason}",
                )

    # --- Create Squid proxy ConfigMap (always — deny-all if no domains) ---
    squid_conf = _build_squid_conf(request)
    try:
        kube.create_configmap(
            namespace=namespace,
            name=f"{request.name}-squid-config",
            data={"squid.conf": squid_conf},
            labels=managed_cm_labels,
        )
        logger.info(
            "Created Squid ConfigMap '%s-squid-config' (domains: %s)",
            request.name,
            request.proxy_domains or request.proxy_allowlist or "DENY ALL",
        )
    except Exception as e:
        logger.warning("Failed to create/update Squid ConfigMap: %s", e)

    # --- Create per-agent egress proxy (Deployment + Service) ---
    proxy_deploy, proxy_svc = _build_egress_proxy_manifests(request)
    try:
        kube.create_deployment(namespace=namespace, body=proxy_deploy)
        logger.info("Created egress proxy Deployment '%s-egress-proxy'", request.name)
    except ApiException as e:
        if e.status == 409:
            logger.info("Egress proxy '%s-egress-proxy' already exists", request.name)
        else:
            logger.warning("Failed to create egress proxy Deployment: %s", e)
    try:
        kube.create_service(namespace=namespace, body=proxy_svc)
        logger.info("Created egress proxy Service '%s-egress-proxy'", request.name)
    except ApiException as e:
        if e.status == 409:
            logger.info("Egress proxy Service already exists")
        else:
            logger.warning("Failed to create egress proxy Service: %s", e)

    # --- Create the agent Deployment ---
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
        message=f"Sandbox agent '{request.name}' ({composable_name}) is being deployed in namespace '{namespace}'",
        composable_name=composable_name,
        security_warnings=security_warnings,
        agent_url=agent_url,
    )


@router.delete("/{namespace}/{name}", response_model=dict)
async def delete_sandbox(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Delete a sandbox agent and all associated resources.

    Cleans up: Deployment, Service, egress-proxy Deployment + Service,
    workspace PVC, squid ConfigMap, and any Secrets created by the wizard.
    """
    deleted: list[str] = []
    errors: list[str] = []

    resources = [
        ("Deployment", name, lambda: kube.apps_api.delete_namespaced_deployment(name, namespace)),
        ("Service", name, lambda: kube.core_api.delete_namespaced_service(name, namespace)),
        (
            "Deployment",
            f"{name}-egress-proxy",
            lambda: kube.apps_api.delete_namespaced_deployment(f"{name}-egress-proxy", namespace),
        ),
        (
            "Service",
            f"{name}-egress-proxy",
            lambda: kube.core_api.delete_namespaced_service(f"{name}-egress-proxy", namespace),
        ),
        (
            "PVC",
            f"{name}-workspace",
            lambda: kube.core_api.delete_namespaced_persistent_volume_claim(
                f"{name}-workspace", namespace
            ),
        ),
        (
            "ConfigMap",
            f"{name}-squid-config",
            lambda: kube.core_api.delete_namespaced_config_map(f"{name}-squid-config", namespace),
        ),
    ]

    for kind, rname, delete_fn in resources:
        try:
            delete_fn()
            deleted.append(f"{kind}/{rname}")
            logger.info("Deleted %s '%s' from namespace '%s'", kind, rname, namespace)
        except ApiException as e:
            if e.status == 404:
                pass  # Already gone
            else:
                errors.append(f"{kind}/{rname}: {e.reason}")
                logger.warning("Failed to delete %s '%s': %s", kind, rname, e)

    return {
        "status": "deleted" if not errors else "partial",
        "deleted": deleted,
        "errors": errors,
    }
