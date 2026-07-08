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
