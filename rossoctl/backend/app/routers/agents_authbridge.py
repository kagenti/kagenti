# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
AuthBridge support for agents.

Covers the sidecar ConfigMaps/RBAC that back AuthBridge (envoy config, SPIFFE
helper config, outbound token-exchange routes) plus the feature-flagged
``identity-config`` / ``identity-status`` endpoints that read the live sidecar.

Split out of ``agents.py``; re-exported there for backwards compatibility.
The routes here are attached to ``authbridge_router`` and composed onto the
main agents router by ``agents.py`` -- see the ordering note there.
"""

import json
import logging
from typing import List

import httpx
import kubernetes.client
import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Path
from kubernetes.client import ApiException

from app.core.auth import ROLE_OPERATOR, require_roles
from app.core.config import settings
from app.core.constants import (
    DEFAULT_ENVOY_YAML,
    DEFAULT_KEYCLOAK_INTERNAL_URL,
    DEFAULT_KEYCLOAK_REALM,
    DEFAULT_SPIFFE_HELPER_CONF,
)
from app.routers.agents_models import OutboundRoute
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.naming import K8S_NAME_MAX_LENGTH, K8S_NAME_PATTERN
from app.utils.routes import detect_platform, sanitize_log

logger = logging.getLogger(__name__)

authbridge_router = APIRouter()


def _get_authbridge_runtime_yaml() -> str:
    """Read the authbridge runtime config from the Helm-managed ConfigMap.

    The pipeline configuration is defined in values.yaml (authBridge.pipeline),
    rendered by the Helm chart into the authbridge-runtime-config ConfigMap,
    and mounted into the backend pod. This is the single source of truth.

    Falls back to legacy in-memory construction when the file does not
    exist (e.g. local development outside the cluster).
    """
    config_path = settings.authbridge_runtime_config_path
    try:
        with open(config_path, "r") as f:
            content = f.read()
        if content.strip():
            return content
    except FileNotFoundError:
        logger.warning(
            "AuthBridge runtime config not found at %s; "
            "falling back to legacy in-memory construction",
            config_path,
        )
    except OSError as e:
        logger.warning(
            "Failed to read AuthBridge runtime config from %s: %s; "
            "falling back to legacy construction",
            config_path,
            e,
        )

    return _build_authbridge_runtime_yaml_fallback()


def _build_authbridge_runtime_yaml(
    keycloak_url: str,
    realm: str,
    issuer: str,
    spire_enabled: bool = False,
) -> str:
    """Build authbridge runtime config YAML with explicit parameters.

    This function is used by tests to generate authbridge configuration
    with specific parameters, independent of the settings object.

    Args:
        keycloak_url: Internal Keycloak URL for JWKS and token exchange
        realm: Keycloak realm name
        issuer: Public issuer URL (must match JWT "iss" claim)
        spire_enabled: Whether to enable SPIFFE/SPIRE identity

    Returns:
        YAML string containing the authbridge runtime configuration
    """
    identity_type = "spiffe" if spire_enabled else "client-secret"
    identity: dict[str, str] = {"type": identity_type}
    if identity_type == "spiffe":
        identity["jwt_audience"] = issuer

    config: dict[str, object] = {}
    if spire_enabled:
        config["spiffe"] = {}

    config["pipeline"] = {
        "inbound": {
            "plugins": [
                {
                    "name": "jwt-validation",
                    "config": {
                        "issuer": issuer,
                        "keycloak_url": keycloak_url,
                        "keycloak_realm": realm,
                    },
                }
            ]
        },
        "outbound": {
            "plugins": [
                {
                    "name": "token-exchange",
                    "config": {
                        "keycloak_url": keycloak_url,
                        "keycloak_realm": realm,
                        "default_policy": "passthrough",
                        "identity": identity,
                    },
                }
            ]
        },
    }

    return yaml.dump(config, default_flow_style=False)


def _build_authbridge_runtime_yaml_fallback() -> str:
    """Legacy fallback: construct authbridge runtime config in-memory.

    Used when the mounted ConfigMap is unavailable (local dev, tests).
    The canonical source of truth is values.yaml authBridge.pipeline,
    rendered by the Helm chart and mounted at the path specified by
    settings.authbridge_runtime_config_path.
    """
    keycloak_url = settings.keycloak_url or DEFAULT_KEYCLOAK_INTERNAL_URL
    realm = settings.effective_keycloak_realm or DEFAULT_KEYCLOAK_REALM
    issuer = f"{settings.effective_keycloak_url}/realms/{realm}"
    spire_enabled = False

    identity_type = "spiffe" if spire_enabled else "client-secret"
    identity: dict[str, str] = {"type": identity_type}
    if identity_type == "spiffe":
        identity["jwt_audience"] = issuer
    config: dict[str, object] = {}
    if spire_enabled:
        config["spiffe"] = {}
    config["pipeline"] = {
        "inbound": {
            "plugins": [
                {
                    "name": "jwt-validation",
                    "config": {
                        "issuer": issuer,
                        "keycloak_url": keycloak_url,
                        "keycloak_realm": realm,
                    },
                }
            ]
        },
        "outbound": {
            "plugins": [
                {
                    "name": "token-exchange",
                    "config": {
                        "keycloak_url": keycloak_url,
                        "keycloak_realm": realm,
                        "default_policy": "passthrough",
                        "identity": identity,
                    },
                }
            ]
        },
    }

    return yaml.dump(config, default_flow_style=False)


def _ensure_authbridge_configmaps(
    kube: KubernetesService,
    namespace: str,
    spire_enabled: bool = False,
) -> None:
    """Ensure the 4 ConfigMaps required by AuthBridge sidecars exist.

    Creates each ConfigMap only if it does not already exist, so user
    customizations (e.g. pointing at a different Keycloak server) are
    preserved on subsequent agent deploys.

    ConfigMaps created:
      - authbridge-config: flat key-value Keycloak URLs for client-registration
      - authbridge-runtime-config: YAML config for the unified authbridge binary
      - envoy-config: Envoy proxy listeners and ext-proc integration
      - spiffe-helper-config: SPIFFE workload API socket paths and SVID output

    For Helm-managed namespaces, the Helm chart creates equivalent
    ConfigMaps at install time (see agent-namespaces.yaml).
    """
    keycloak_url = settings.keycloak_url or DEFAULT_KEYCLOAK_INTERNAL_URL
    realm = settings.effective_keycloak_realm or DEFAULT_KEYCLOAK_REALM
    # ISSUER must use the public/external URL because it must match the
    # "iss" claim in JWT tokens issued by Keycloak (split-horizon DNS).
    issuer = f"{settings.effective_keycloak_url}/realms/{realm}"

    # 1. authbridge-config (flat key-value for client-registration and legacy go-processor)
    kube.ensure_configmap(
        namespace=namespace,
        name="authbridge-config",
        data={
            "KEYCLOAK_URL": keycloak_url,
            "KEYCLOAK_REALM": realm,
            "ISSUER": issuer,
            "SPIRE_ENABLED": "true" if spire_enabled else "false",
        },
    )

    # 2. authbridge-runtime-config (YAML config for the unified authbridge binary)
    # The operator reads this at admission time and creates a per-agent ConfigMap
    # with mode and listener addresses merged in.
    # Source of truth: values.yaml authBridge.pipeline → Helm renders ConfigMap →
    # mounted into this pod → _get_authbridge_runtime_yaml() reads it.
    kube.ensure_configmap(
        namespace=namespace,
        name="authbridge-runtime-config",
        data={"config.yaml": _get_authbridge_runtime_yaml()},
    )

    # 3. envoy-config
    kube.ensure_configmap(
        namespace=namespace,
        name="envoy-config",
        data={"envoy.yaml": DEFAULT_ENVOY_YAML},
    )

    # 4. spiffe-helper-config
    kube.ensure_configmap(
        namespace=namespace,
        name="spiffe-helper-config",
        data={"helper.conf": DEFAULT_SPIFFE_HELPER_CONF},
    )

    logger.info(f"Ensured AuthBridge ConfigMaps in namespace '{namespace}'")


def _ensure_authproxy_routes(
    kube: KubernetesService,
    namespace: str,
    routes: List["OutboundRoute"],
) -> None:
    """Create or update the authproxy-routes ConfigMap with outbound token exchange rules."""
    # AuthProxy go-processor expects a YAML list at file root (static.go), not {"routes": [...]}.
    routes_list = [r.model_dump() for r in routes]
    kube.upsert_configmap(
        namespace=namespace,
        name="authproxy-routes",
        data={"routes.yaml": yaml.dump(routes_list, default_flow_style=False)},
    )
    logger.info(
        "Upserted authproxy-routes ConfigMap in namespace '%s' with %d route(s)",
        namespace,
        len(routes),
    )


def _ensure_authbridge_scc_rolebinding(
    kube: KubernetesService,
    namespace: str,
) -> None:
    """On OpenShift, ensure the AuthBridge SCC RoleBinding exists.

    AuthBridge sidecars need NET_ADMIN/NET_RAW capabilities, RunAsAny UIDs,
    and CSI volumes that OpenShift's default restricted-v2 SCC blocks.
    The Helm chart creates the ``rossoctl-authbridge`` SCC and its ClusterRole;
    this function creates the per-namespace RoleBinding that grants it to all
    service accounts in the namespace.

    On non-OpenShift clusters this is a no-op.  If the ClusterRole doesn't
    exist (SCC not installed), a warning is logged and the function returns
    without error — the agent will still be created, but pods may fail with
    SCC errors until the SCC is installed.
    """
    if detect_platform(kube) != "openshift":
        return

    cluster_role_name = "system:openshift:scc:rossoctl-authbridge"

    # Verify the ClusterRole exists (implies the SCC was installed)
    try:
        kube.rbac_api.read_cluster_role(name=cluster_role_name)
    except ApiException as e:
        if e.status == 404:
            logger.warning(
                "ClusterRole '%s' not found. "
                "The rossoctl-authbridge SCC may not be installed. "
                "Agent pods may fail with SCC errors. "
                "Install via: helm upgrade rossoctl charts/rossoctl --set openshift=true",
                cluster_role_name,
            )
            return
        raise

    kube.ensure_rolebinding(
        namespace=namespace,
        name="agent-authbridge-scc",
        cluster_role_name=cluster_role_name,
        subjects=[
            kubernetes.client.RbacV1Subject(
                kind="Group",
                api_group="rbac.authorization.k8s.io",
                name=f"system:serviceaccounts:{namespace}",
            ),
        ],
    )


def _get_service_endpoints(kube: KubernetesService, namespace: str, name: str) -> List[str]:
    """
    Get addresses for a K8s service
    """

    addresses: list[str] = []
    endpoint_slices = kube.get_endpoint_slices(namespace=namespace, name=name)

    for endpoint_slice in endpoint_slices.get("items", []):
        for endpoint in endpoint_slice.get("endpoints", []):
            for address in endpoint.get("addresses", []):
                addresses.append(address)

    return addresses


async def _fetch_authbridge_json(url: str) -> dict:
    """
    Fetch JSON from an AuthBridge sidecar endpoint.

    Raises on HTTP errors, oversized responses, or non-dict payloads.
    """

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        logger.debug("Making HTTP request to %s", url)
        response = await client.get(url)
        response.raise_for_status()

        content = response.text
        if len(content) > 1024 * 1024:
            raise HTTPException(status_code=502, detail="File content too large (max 1MB)")

        data = json.loads(content)
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="File content not AuthBridge JSON")

        return data


if settings.rossoctl_feature_flag_authbridge_api:

    @authbridge_router.get(
        "/{namespace}/{name}/identity-config", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
    )
    async def get_agent_identity_config(
        namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        kube: KubernetesService = Depends(get_kubernetes_service),
    ) -> dict:
        """
        Fetch the AuthBridge configuration for an Agent.
        """

        namespace = sanitize_log(namespace)
        name = sanitize_log(name)

        try:
            addresses = _get_service_endpoints(kube=kube, namespace=namespace, name=name)
        except ApiException as e:
            raise HTTPException(status_code=502, detail=e.reason)

        attempts = 0
        for address in addresses:
            attempts += 1
            # AuthBridge serves config and status on port 9093
            url = f"http://{address}:9093/config"
            try:
                data = await _fetch_authbridge_json(url)
                data["AuthBridge"] = True
                return data
            except Exception:
                # It isn't an error for an endpoint to be unreachable, only for all pods to be unreachable
                logger.info("Failed to talk to url %s; skipping", url, exc_info=True)

        if attempts == 0:
            raise HTTPException(status_code=404, detail=f"{name} not found")

        logger.info("Could not invoke any AuthBridge endpoints for %s/%s", namespace, name)
        # We return HTTP 200 if no pods respond - this might be a valid agent w/o AuthBridge
        return {"AuthBridge": False}

    @authbridge_router.put(
        "/{namespace}/{name}/identity-config", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
    )
    async def put_agent_identity_config(
        namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        new_authbridge_config_yaml: str = Body(media_type="text/plain"),
        kube: KubernetesService = Depends(get_kubernetes_service),
    ) -> dict:
        """
        Set the AuthBridge configuration for an Agent.
        """

        try:
            yaml.safe_load(new_authbridge_config_yaml)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}") from e

        kube.upsert_configmap(
            namespace=namespace,
            name=f"authbridge-config-{name}",
            data={"config.yaml": new_authbridge_config_yaml},
        )

        return {"status": "ok"}

    @authbridge_router.get(
        "/{namespace}/{name}/identity-status", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
    )
    async def get_agent_identity_status(
        namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
        kube: KubernetesService = Depends(get_kubernetes_service),
    ) -> dict:
        """
        Fetch the AuthBridge statistics and status for an Agent.
        """

        namespace = sanitize_log(namespace)
        name = sanitize_log(name)

        try:
            addresses = _get_service_endpoints(kube=kube, namespace=namespace, name=name)
        except ApiException as e:
            raise HTTPException(status_code=502, detail=e.reason)

        attempts = 0
        for address in addresses:
            attempts += 1
            # AuthBridge serves config and status on port 9093
            url = f"http://{address}:9093/stats"
            try:
                data = await _fetch_authbridge_json(url)
                data["AuthBridge"] = True
                return data
            except Exception:
                # It isn't an error for an endpoint to be unreachable, only for all pods to be unreachable
                logger.info("Failed to talk to url %s; skipping", url, exc_info=True)

        if attempts == 0:
            raise HTTPException(status_code=404, detail=f"{name} not found")

        logger.info("Could not invoke any AuthBridge endpoints for %s/%s", namespace, name)
        # We return HTTP 200 if no pods respond - this might be a valid agent w/o AuthBridge
        return {"AuthBridge": False}
