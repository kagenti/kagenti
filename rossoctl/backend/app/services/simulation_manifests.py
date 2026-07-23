# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Pure builders for simulated-tool Kubernetes manifests (epic #2151, issue #2161).

Standalone by design — no changes to app/routers/tools.py. A parity test
(tests/test_simulation_manifests.py) guards the identity/mesh/security surface
against drift from the tool builders.
"""

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from app.core.constants import (
    APP_KUBERNETES_IO_MANAGED_BY,
    APP_KUBERNETES_IO_NAME,
    CRD_GROUP,
    CRD_VERSION,
    DEFAULT_ENV_VARS,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_RESOURCE_REQUESTS,
    ROSSOCTL_AUTOSCALING_ANNOTATION,
    ROSSOCTL_DESCRIPTION_ANNOTATION,
    ROSSOCTL_FRAMEWORK_LABEL,
    ROSSOCTL_INJECT_LABEL,
    ROSSOCTL_SIMULATED_LABEL,
    ROSSOCTL_SPIRE_ENABLED_VALUE,
    ROSSOCTL_SPIRE_LABEL,
    ROSSOCTL_TRANSPORT_LABEL,
    ROSSOCTL_TYPE_LABEL,
    ROSSOCTL_UI_CREATOR_LABEL,
    ROSSOCTL_WORKLOAD_TYPE_LABEL,
    PROTOCOL_LABEL_PREFIX,
    RESOURCE_TYPE_TOOL,
    SIMULATION_HARNESS_SKILLS_MOUNT,
    TOOL_SERVICE_SUFFIX,
    VALUE_PROTOCOL_MCP,
    VALUE_TRANSPORT_STREAMABLE_HTTP,
    WORKLOAD_TYPE_STATEFULSET,
)

_MCP_PROTOCOL_LABEL = f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}"

# DNS-1123 label: lowercase alphanumeric and '-', must start and end alphanumeric.
_DNS1123_LABEL_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
# A simulated tool's Service is named "{name}-mcp" and must itself be a valid
# DNS-1123 label (<=63), so the tool name is capped to leave room for the suffix.
MAX_SIMULATION_NAME_LEN = 63 - len(TOOL_SERVICE_SUFFIX)
# Kubernetes resource quantity, e.g. "1Gi", "500Mi", "2G".
_QUANTITY_RE = re.compile(r"^[1-9][0-9]*(\.[0-9]+)?(Ei|Pi|Ti|Gi|Mi|Ki|E|P|T|G|M|k)?$")


def _is_dns1123_label(value: str) -> bool:
    """Return True if value is a valid DNS-1123 label (<=63 chars)."""
    return bool(value) and len(value) <= 63 and _DNS1123_LABEL_RE.match(value) is not None


def validate_namespace(namespace: str) -> str:
    """Validate a target namespace as a DNS-1123 label. Raises ValueError if invalid."""
    if not _is_dns1123_label(namespace):
        raise ValueError(
            "namespace must be a DNS-1123 label: lowercase alphanumeric or '-', "
            "start and end alphanumeric, at most 63 characters"
        )
    return namespace


def validate_storage_size(size: str) -> str:
    """Validate a PVC storage size as a Kubernetes quantity. Raises ValueError if invalid."""
    if not _QUANTITY_RE.match(size):
        raise ValueError("storageSize must be a Kubernetes quantity, e.g. '1Gi', '500Mi', '2G'")
    return size


def validate_custom_name(name: str) -> str:
    """Validate a user-supplied tool name (reject rather than silently mutate).

    Must be a DNS-1123 label short enough that the derived "{name}-mcp" Service
    name stays a valid label. Raises ValueError if invalid.
    """
    if not _is_dns1123_label(name) or len(name) > MAX_SIMULATION_NAME_LEN:
        raise ValueError(
            "name must be a DNS-1123 label (lowercase alphanumeric or '-', start and end "
            f"alphanumeric) of at most {MAX_SIMULATION_NAME_LEN} characters"
        )
    return name


class SecretKeyRef(BaseModel):
    """Reference to a key in a Secret."""

    name: str
    key: str


class ConfigMapKeyRef(BaseModel):
    """Reference to a key in a ConfigMap."""

    name: str
    key: str


class EnvVarSource(BaseModel):
    """Source for an environment variable value."""

    secretKeyRef: Optional[SecretKeyRef] = None
    configMapKeyRef: Optional[ConfigMapKeyRef] = None


class EnvVar(BaseModel):
    """Environment variable with support for direct values and references."""

    name: str
    value: Optional[str] = None
    valueFrom: Optional[EnvVarSource] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", v or ""):
            raise ValueError(
                f"Invalid environment variable name '{v}'. Must start with a letter or "
                "underscore and contain only letters, digits, and underscores."
            )
        return v


def build_simulation_env_vars(
    env_var_list: Optional[List[EnvVar]] = None,
    *,
    port: int = DEFAULT_IN_CLUSTER_PORT,
    skills_folder: str = SIMULATION_HARNESS_SKILLS_MOUNT,
) -> List[dict]:
    """Build the harness container env: platform defaults + harness config + user vars.

    User-supplied vars (e.g. LLM_API_KEY via secretKeyRef) win on name collision.
    """
    env_vars: List[dict] = list(DEFAULT_ENV_VARS)
    env_vars.append({"name": "HARNESS_SKILLS_FOLDER", "value": skills_folder})
    env_vars.append({"name": "HARNESS_SERVER_PORT", "value": str(port)})
    env_vars.append({"name": "HARNESS_SERVER_HOST", "value": "0.0.0.0"})
    # Serve MCP over streamable-http to match the ROSSOCTL_TRANSPORT_LABEL the
    # StatefulSet/pod advertise (and the MCP gateway/clients expect). Without
    # this the harness falls back to its bundled SSE config default.
    env_vars.append({"name": "HARNESS_MCP_TRANSPORT", "value": "streamable_http"})
    # The harness defaults startup.autostart_enabled=false (boots idle, ignores
    # the skill baked on the PVC). Rossoctl bakes exactly one skill per StatefulSet
    # and relies on the harness resuming it on every (re)start — Stop->Start
    # (scale 0->1) and involuntary pod restarts both depend on boot-time
    # autostart. Opt back in; autostart_simulation is left unset so the harness's
    # "1 complete skill -> start it, 0 -> idle" discovery stays graceful.
    env_vars.append({"name": "HARNESS_AUTOSTART_ENABLED", "value": "true"})

    for ev in env_var_list or []:
        if ev.value is not None:
            env_vars.append({"name": ev.name, "value": ev.value})
        elif ev.valueFrom is not None:
            entry: Dict[str, Any] = {"name": ev.name, "valueFrom": {}}
            if ev.valueFrom.secretKeyRef:
                entry["valueFrom"]["secretKeyRef"] = {
                    "name": ev.valueFrom.secretKeyRef.name,
                    "key": ev.valueFrom.secretKeyRef.key,
                }
            elif ev.valueFrom.configMapKeyRef:
                entry["valueFrom"]["configMapKeyRef"] = {
                    "name": ev.valueFrom.configMapKeyRef.name,
                    "key": ev.valueFrom.configMapKeyRef.key,
                }
            env_vars.append(entry)

    seen: Dict[str, dict] = {}
    for env in env_vars:
        seen[env["name"]] = env
    return list(seen.values())


def build_simulation_statefulset(
    name: str,
    namespace: str,
    image: str,
    *,
    env_vars: List[dict],
    port: int = DEFAULT_IN_CLUSTER_PORT,
    storage_size: str = "1Gi",
    skills_folder: str = SIMULATION_HARNESS_SKILLS_MOUNT,
    framework: str = "Python",
    description: str = "",
    spire_enabled: bool = False,
    auth_bridge_enabled: bool = False,
    auth_bridge_mode: Optional[str] = None,
    image_pull_secret: Optional[str] = None,
    image_pull_policy: str = "Always",
) -> dict:
    """Build a StatefulSet manifest for a simulated tool (replicas 1, HPA off)."""
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    inject = "enabled" if auth_bridge_enabled else "disabled"

    # NOTE: rossoctl.io/type is intentionally NOT set here. The
    # agent-label-protection ValidatingAdmissionPolicy forbids any principal but
    # the operator SA from setting it on a Deployment/StatefulSet. The workload is
    # created bare and adopted by an AgentRuntime CR (build_simulation_agentruntime);
    # the operator stamps rossoctl.io/type=tool onto the workload during
    # reconciliation. This mirrors the regular-tool path.
    labels = {
        APP_KUBERNETES_IO_NAME: name,
        _MCP_PROTOCOL_LABEL: "",
        ROSSOCTL_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        ROSSOCTL_FRAMEWORK_LABEL: framework,
        ROSSOCTL_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_STATEFULSET,
        ROSSOCTL_SIMULATED_LABEL: "true",
        APP_KUBERNETES_IO_MANAGED_BY: ROSSOCTL_UI_CREATOR_LABEL,
        ROSSOCTL_INJECT_LABEL: inject,
    }
    pod_labels = {
        APP_KUBERNETES_IO_NAME: name,
        _MCP_PROTOCOL_LABEL: "",
        ROSSOCTL_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        ROSSOCTL_FRAMEWORK_LABEL: framework,
        ROSSOCTL_SIMULATED_LABEL: "true",
        ROSSOCTL_INJECT_LABEL: inject,
    }
    if spire_enabled:
        labels[ROSSOCTL_SPIRE_LABEL] = ROSSOCTL_SPIRE_ENABLED_VALUE
        pod_labels[ROSSOCTL_SPIRE_LABEL] = ROSSOCTL_SPIRE_ENABLED_VALUE

    annotations = {ROSSOCTL_AUTOSCALING_ANNOTATION: "disabled"}
    if description:
        annotations[ROSSOCTL_DESCRIPTION_ANNOTATION] = description
    pod_annotations: Dict[str, str] = {}
    if auth_bridge_mode:
        pod_annotations["rossoctl.io/authbridge-mode"] = auth_bridge_mode

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "serviceName": service_name,
            "replicas": 1,
            "selector": {"matchLabels": {APP_KUBERNETES_IO_NAME: name}},
            "template": {
                "metadata": {"labels": pod_labels, "annotations": pod_annotations},
                "spec": {
                    "serviceAccountName": name,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                        # Make the RWO PVC (mounted at skills_folder) group-writable
                        # by the harness runtime UID. The image runs as uid 1000 and
                        # its entrypoint no longer chowns when already non-root, so
                        # without fsGroup the uid-1000 process cannot write the PVC.
                        "fsGroup": 1000,
                    },
                    "containers": [
                        {
                            "name": "harness",
                            "image": image,
                            "imagePullPolicy": image_pull_policy,
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsUser": 1000,
                            },
                            "env": env_vars,
                            "ports": [{"containerPort": port, "name": "http"}],
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/readyz", "port": port},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": "/healthz", "port": port},
                                "initialDelaySeconds": 10,
                                "periodSeconds": 20,
                            },
                            "volumeMounts": [
                                {"name": "data", "mountPath": skills_folder},
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": storage_size}},
                    },
                }
            ],
        },
    }
    if image_pull_secret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [{"name": image_pull_secret}]
    return manifest


def build_simulation_service(
    name: str,
    namespace: str,
    *,
    port: int = DEFAULT_IN_CLUSTER_PORT,
) -> dict:
    """Build a ClusterIP Service manifest for a simulated tool ({name}-mcp)."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"{name}{TOOL_SERVICE_SUFFIX}",
            "namespace": namespace,
            "labels": {
                _MCP_PROTOCOL_LABEL: "",
                APP_KUBERNETES_IO_NAME: name,
                APP_KUBERNETES_IO_MANAGED_BY: ROSSOCTL_UI_CREATOR_LABEL,
                ROSSOCTL_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                ROSSOCTL_SIMULATED_LABEL: "true",
            },
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {APP_KUBERNETES_IO_NAME: name},
            "ports": [{"name": "http", "port": port, "targetPort": port, "protocol": "TCP"}],
        },
    }


def build_simulation_agentruntime(
    name: str,
    namespace: str,
    *,
    auth_bridge_mode: Optional[str] = None,
) -> dict:
    """Build an AgentRuntime CR that adopts the simulated-tool StatefulSet.

    The StatefulSet is created without the ``rossoctl.io/type`` label because the
    agent-label-protection ValidatingAdmissionPolicy only lets the operator SA set
    it. This CR references the workload via ``spec.targetRef``; the operator adopts
    the StatefulSet and stamps ``rossoctl.io/type=tool`` (plus its config-hash /
    mtls annotations) as the exempt controller-manager SA — the same mechanism the
    regular-tool path uses (``app.routers.tools._ensure_tool_agentruntime``).

    Kept here rather than imported from app.routers.tools so this module stays
    standalone (see module docstring). The CR shape is CRD-stable (required fields
    are only ``type`` and ``targetRef``).
    """
    manifest: Dict[str, Any] = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "AgentRuntime",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                APP_KUBERNETES_IO_NAME: name,
                APP_KUBERNETES_IO_MANAGED_BY: ROSSOCTL_UI_CREATOR_LABEL,
                ROSSOCTL_SIMULATED_LABEL: "true",
            },
        },
        "spec": {
            "type": RESOURCE_TYPE_TOOL,
            "targetRef": {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "name": name,
            },
        },
    }
    if auth_bridge_mode:
        manifest["spec"]["authBridgeMode"] = auth_bridge_mode
    return manifest


def validate_openapi_spec(text: str) -> dict:
    """Syntactic validation only: parse the spec as a JSON object.

    The harness validates the OpenAPI schema itself; Rossoctl only rejects a
    syntactically invalid spec (non-JSON or not a JSON object) so no workload
    is created for garbage input. Raises ValueError on failure.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"OpenAPI spec is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI spec must be a JSON object")
    return parsed


def derive_simulation_name(spec: dict, requested: Optional[str]) -> str:
    """Return a Kubernetes-safe name: requested if given, else slug of info.title."""
    candidate = requested or (spec.get("info", {}) or {}).get("title", "") or ""
    slug = (
        re.sub(r"[^a-z0-9]+", "-", candidate.lower())
        .strip("-")[:MAX_SIMULATION_NAME_LEN]
        .rstrip("-")
    )
    return slug or "simulated-tool"
