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
    DEFAULT_ENV_VARS,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_RESOURCE_REQUESTS,
    KAGENTI_AUTOSCALING_ANNOTATION,
    KAGENTI_DESCRIPTION_ANNOTATION,
    KAGENTI_FRAMEWORK_LABEL,
    KAGENTI_INJECT_LABEL,
    KAGENTI_SIMULATED_LABEL,
    KAGENTI_SPIRE_ENABLED_VALUE,
    KAGENTI_SPIRE_LABEL,
    KAGENTI_TRANSPORT_LABEL,
    KAGENTI_TYPE_LABEL,
    KAGENTI_UI_CREATOR_LABEL,
    KAGENTI_WORKLOAD_TYPE_LABEL,
    PROTOCOL_LABEL_PREFIX,
    RESOURCE_TYPE_TOOL,
    SIMULATION_HARNESS_SKILLS_MOUNT,
    TOOL_SERVICE_SUFFIX,
    VALUE_PROTOCOL_MCP,
    VALUE_TRANSPORT_STREAMABLE_HTTP,
    WORKLOAD_TYPE_STATEFULSET,
)

_MCP_PROTOCOL_LABEL = f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}"


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
) -> dict:
    """Build a StatefulSet manifest for a simulated tool (replicas 1, HPA off)."""
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    inject = "enabled" if auth_bridge_enabled else "disabled"

    labels = {
        APP_KUBERNETES_IO_NAME: name,
        _MCP_PROTOCOL_LABEL: "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_STATEFULSET,
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        KAGENTI_SIMULATED_LABEL: "true",
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
        KAGENTI_INJECT_LABEL: inject,
    }
    pod_labels = {
        APP_KUBERNETES_IO_NAME: name,
        _MCP_PROTOCOL_LABEL: "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        KAGENTI_SIMULATED_LABEL: "true",
        KAGENTI_INJECT_LABEL: inject,
    }
    if spire_enabled:
        labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
        pod_labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE

    annotations = {KAGENTI_AUTOSCALING_ANNOTATION: "disabled"}
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description
    pod_annotations: Dict[str, str] = {}
    if auth_bridge_mode:
        pod_annotations["kagenti.io/authbridge-mode"] = auth_bridge_mode

    return {
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
                    },
                    "containers": [
                        {
                            "name": "harness",
                            "image": image,
                            "imagePullPolicy": "Always",
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
                APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
                KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                KAGENTI_SIMULATED_LABEL: "true",
            },
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {APP_KUBERNETES_IO_NAME: name},
            "ports": [{"name": "http", "port": port, "targetPort": port, "protocol": "TCP"}],
        },
    }


def validate_openapi_spec(text: str) -> dict:
    """Syntactic validation only: parse the spec as a JSON object.

    The harness validates the OpenAPI schema itself; Kagenti only rejects a
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
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")[:63].rstrip("-")
    return slug or "simulated-tool"
