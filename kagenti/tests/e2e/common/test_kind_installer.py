#!/usr/bin/env python3
"""
Kind Installer E2E Tests — verify setup-kagenti.sh --with-* flags.

Auto-detects which flags were used by querying Helm releases and deployments,
then verifies:
  1. Core components are always present (cert-manager, Gateway API, Istio GW, Keycloak)
  2. Each --with-* flag installs its expected components
  3. Flag dependencies are honored (e.g. --with-mlflow → --with-istio + --with-otel)
  4. Components NOT requested are NOT deployed

Override auto-detection via env var:
    KIND_INSTALLER_FLAGS="--with-istio --with-ui" pytest ...

Usage:
    # After running setup-kagenti.sh with any flags:
    uv run pytest kagenti/tests/e2e/common/test_kind_installer.py -v
"""

import json
import os
import subprocess

import pytest
from kubernetes.client.rest import ApiException


def _cluster_reachable():
    """Check if a Kubernetes cluster is reachable via kubectl."""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


pytestmark = [
    pytest.mark.kind_only,
    pytest.mark.skipif(
        not _cluster_reachable(),
        reason="No Kubernetes cluster reachable — skipping Kind installer tests",
    ),
]


# ============================================================================
# Flag ↔ Component Mapping
# ============================================================================

# Helm releases that indicate a specific --with-* flag was used
RELEASE_TO_FLAG = {
    "istio-cni": "istio",
    "ztunnel": "istio",
    "spire-crds": "spire",
    "spire": "spire",
    "mcp-gateway": "mcp_gateway",
    "kuadrant-operator": "kuadrant",
}

# Deployments that indicate a specific --with-* flag was used
DEPLOYMENT_TO_FLAG = {
    ("kagenti-backend", "kagenti-system"): "backend",
    ("kagenti-ui", "kagenti-system"): "ui",
    ("mlflow", "kagenti-system"): "mlflow",
    ("kiali", "istio-system"): "kiali",
    ("otel-collector", "kagenti-system"): "otel",
    ("tekton-pipelines-controller", "tekton-pipelines"): "builds",
}

# Expected Helm releases per flag (name, namespace)
FLAG_RELEASES = {
    "core": [
        ("istio-base", "istio-system"),
        ("istiod", "istio-system"),
        ("kagenti-deps", "kagenti-system"),
        ("kagenti", "kagenti-system"),
    ],
    "istio": [
        ("istio-cni", "istio-system"),
        ("ztunnel", "istio-system"),
    ],
    "spire": [
        ("spire-crds", "spire-mgmt"),
        ("spire", "spire-mgmt"),
    ],
    "mcp_gateway": [
        ("mcp-gateway", "mcp-system"),
    ],
    "kuadrant": [
        ("kuadrant-operator", "kuadrant-system"),
    ],
}

# Expected deployments per flag (name, namespace)
FLAG_DEPLOYMENTS = {
    "core": [
        ("cert-manager", "cert-manager"),
        ("cert-manager-webhook", "cert-manager"),
        ("istiod", "istio-system"),
    ],
    "backend": [
        ("kagenti-backend", "kagenti-system"),
    ],
    "ui": [
        ("kagenti-ui", "kagenti-system"),
    ],
    "otel": [
        ("otel-collector", "kagenti-system"),
    ],
    "mlflow": [
        ("mlflow", "kagenti-system"),
    ],
    "kiali": [
        ("kiali", "istio-system"),
        ("prometheus", "istio-system"),
    ],
    "builds": [
        ("tekton-pipelines-controller", "tekton-pipelines"),
        ("registry", "cr-system"),
    ],
}

# Auto-enable dependencies (mirrors setup-kagenti.sh flag dependencies)
FLAG_DEPENDENCIES = {
    "ui": ["backend"],
    "kiali": ["istio"],
    "mlflow": ["istio", "otel"],
    "kuadrant": ["mcp_gateway"],
}


# ============================================================================
# Fixtures
# ============================================================================


def _run_helm_list():
    """Run helm list and return parsed JSON."""
    try:
        result = subprocess.run(
            ["helm", "list", "-A", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _deployment_exists(k8s_apps_client, name, namespace):
    """Check if a deployment exists (without raising)."""
    try:
        k8s_apps_client.read_namespaced_deployment(name=name, namespace=namespace)
        return True
    except ApiException:
        return False


@pytest.fixture(scope="module")
def helm_releases():
    """Get all Helm releases as a dict keyed by (name, namespace)."""
    releases = _run_helm_list()
    return {(r["name"], r["namespace"]): r.get("status", "unknown") for r in releases}


@pytest.fixture(scope="module")
def installed_flags(helm_releases, k8s_apps_client):
    """
    Detect which --with-* flags were used based on cluster state.

    Returns a set of flag names like {"istio", "spire", "backend", "ui", "mlflow"}.
    Override with KIND_INSTALLER_FLAGS env var.
    """
    env_flags = os.getenv("KIND_INSTALLER_FLAGS", "").strip()
    if env_flags:
        flags = set()
        for token in env_flags.split():
            token = token.strip()
            if token.startswith("--with-"):
                flag = token[len("--with-") :].replace("-", "_")
                flags.add(flag)
                if flag == "all":
                    flags.update(
                        [
                            "istio",
                            "spire",
                            "backend",
                            "ui",
                            "mcp_gateway",
                            "kuadrant",
                            "otel",
                            "mlflow",
                            "builds",
                            "kiali",
                        ]
                    )
        for flag in list(flags):
            for dep in FLAG_DEPENDENCIES.get(flag, []):
                flags.add(dep)
        return flags

    flags = set()

    for (release_name, _ns), status in helm_releases.items():
        if status == "deployed" and release_name in RELEASE_TO_FLAG:
            flags.add(RELEASE_TO_FLAG[release_name])

    for (deploy_name, deploy_ns), flag in DEPLOYMENT_TO_FLAG.items():
        if _deployment_exists(k8s_apps_client, deploy_name, deploy_ns):
            flags.add(flag)

    return flags


# ============================================================================
# Helpers
# ============================================================================


def _assert_helm_release(helm_releases, name, namespace):
    """Assert a Helm release exists and is deployed."""
    key = (name, namespace)
    assert key in helm_releases, (
        f"Helm release '{name}' not found in namespace '{namespace}'. "
        f"Deployed releases: {sorted(helm_releases.keys())}"
    )
    status = helm_releases[key]
    assert status == "deployed", (
        f"Helm release '{name}' ({namespace}) status is '{status}', expected 'deployed'"
    )


def _assert_no_helm_release(helm_releases, name, namespace):
    """Assert a Helm release does NOT exist."""
    key = (name, namespace)
    if key in helm_releases:
        status = helm_releases[key]
        assert status != "deployed", (
            f"Helm release '{name}' ({namespace}) should not be deployed "
            f"but has status '{status}'"
        )


def _assert_deployment_ready(k8s_apps_client, name, namespace):
    """Assert a deployment exists and has ready replicas."""
    try:
        deployment = k8s_apps_client.read_namespaced_deployment(
            name=name, namespace=namespace
        )
    except ApiException as e:
        pytest.fail(f"Deployment '{name}' not found in '{namespace}': {e.reason}")

    desired = deployment.spec.replicas or 1
    ready = deployment.status.ready_replicas or 0
    assert ready >= desired, (
        f"Deployment '{name}' ({namespace}) not ready: {ready}/{desired} replicas"
    )


def _assert_statefulset_ready(k8s_apps_client, name, namespace):
    """Assert a statefulset exists and has ready replicas."""
    try:
        sts = k8s_apps_client.read_namespaced_stateful_set(
            name=name, namespace=namespace
        )
    except ApiException as e:
        pytest.fail(f"StatefulSet '{name}' not found in '{namespace}': {e.reason}")

    desired = sts.spec.replicas or 1
    ready = sts.status.ready_replicas or 0
    assert ready >= desired, (
        f"StatefulSet '{name}' ({namespace}) not ready: {ready}/{desired} replicas"
    )


def _assert_workload_ready(k8s_apps_client, name, namespace):
    """Assert a deployment or statefulset exists and is ready."""
    deploy_exists = True
    try:
        k8s_apps_client.read_namespaced_deployment(name=name, namespace=namespace)
    except ApiException:
        deploy_exists = False

    if deploy_exists:
        _assert_deployment_ready(k8s_apps_client, name, namespace)
        return

    _assert_statefulset_ready(k8s_apps_client, name, namespace)


def _assert_no_deployment(k8s_apps_client, name, namespace):
    """Assert a deployment does NOT exist."""
    try:
        k8s_apps_client.read_namespaced_deployment(name=name, namespace=namespace)
        pytest.fail(
            f"Deployment '{name}' exists in '{namespace}' but should not be deployed"
        )
    except ApiException as e:
        assert e.status == 404, f"Unexpected error checking '{name}': {e.reason}"


def _skip_if_flag(installed_flags, flag):
    """Skip test if flag IS set (for negative tests)."""
    if flag in installed_flags:
        pytest.skip(f"--with-{flag.replace('_', '-')} was used")


def _skip_unless_flag(installed_flags, flag):
    """Skip test if flag is NOT set (for positive tests)."""
    if flag not in installed_flags:
        pytest.skip(f"--with-{flag.replace('_', '-')} not used")


# ============================================================================
# Core Components (always installed)
# ============================================================================


@pytest.mark.kind_only
class TestCoreComponents:
    """Core components that are always installed regardless of flags."""

    @pytest.mark.critical
    def test_cert_manager_deployed(self, k8s_apps_client):
        """cert-manager webhook must be ready (Step 2)."""
        _assert_deployment_ready(
            k8s_apps_client, "cert-manager-webhook", "cert-manager"
        )

    @pytest.mark.critical
    def test_gateway_api_crds_established(self, k8s_client):
        """Gateway API CRDs must be established (Step 5)."""
        from kubernetes.client import ApiextensionsV1Api
        from kubernetes import config

        try:
            config.load_kube_config()
        except config.ConfigException:
            config.load_incluster_config()

        api = ApiextensionsV1Api()

        for crd_name in [
            "httproutes.gateway.networking.k8s.io",
            "gateways.gateway.networking.k8s.io",
        ]:
            try:
                crd = api.read_custom_resource_definition(name=crd_name)
            except ApiException:
                pytest.fail(f"CRD '{crd_name}' not found")

            conditions = {c.type: c.status for c in (crd.status.conditions or [])}
            assert conditions.get("Established") == "True", (
                f"CRD '{crd_name}' not established: {conditions}"
            )

    @pytest.mark.critical
    def test_istio_base_release(self, helm_releases):
        """istio-base Helm release must be deployed (Step 3)."""
        _assert_helm_release(helm_releases, "istio-base", "istio-system")

    @pytest.mark.critical
    def test_istiod_release(self, helm_releases):
        """istiod Helm release must be deployed (Step 3)."""
        _assert_helm_release(helm_releases, "istiod", "istio-system")

    @pytest.mark.critical
    def test_istiod_deployment_ready(self, k8s_apps_client):
        """istiod deployment must be ready."""
        _assert_deployment_ready(k8s_apps_client, "istiod", "istio-system")

    @pytest.mark.critical
    def test_keycloak_ready(self, k8s_apps_client):
        """Keycloak must be ready (deployed by kagenti-deps as Deployment or StatefulSet)."""
        _assert_workload_ready(k8s_apps_client, "keycloak", "keycloak")

    @pytest.mark.critical
    def test_keycloak_namespace_exists(self, k8s_client):
        """Keycloak namespace must exist."""
        try:
            k8s_client.read_namespace(name="keycloak")
        except ApiException:
            pytest.fail("keycloak namespace not found")

    @pytest.mark.critical
    def test_kagenti_deps_release(self, helm_releases):
        """kagenti-deps Helm release must be deployed (Step 6)."""
        _assert_helm_release(helm_releases, "kagenti-deps", "kagenti-system")

    @pytest.mark.critical
    def test_kagenti_release(self, helm_releases):
        """kagenti Helm release must be deployed (Step 8)."""
        _assert_helm_release(helm_releases, "kagenti", "kagenti-system")


# ============================================================================
# Istio Ambient (--with-istio)
# ============================================================================


@pytest.mark.kind_only
class TestIstioAmbient:
    """Components installed by --with-istio (ambient mesh overlay)."""

    def test_istio_cni_release(self, installed_flags, helm_releases):
        """istio-cni release deployed when --with-istio."""
        _skip_unless_flag(installed_flags, "istio")
        _assert_helm_release(helm_releases, "istio-cni", "istio-system")

    def test_ztunnel_release(self, installed_flags, helm_releases):
        """ztunnel release deployed when --with-istio."""
        _skip_unless_flag(installed_flags, "istio")
        _assert_helm_release(helm_releases, "ztunnel", "istio-system")

    def test_ambient_not_installed_without_flag(self, installed_flags, helm_releases):
        """istio-cni and ztunnel must NOT be deployed without --with-istio."""
        _skip_if_flag(installed_flags, "istio")
        _assert_no_helm_release(helm_releases, "istio-cni", "istio-system")
        _assert_no_helm_release(helm_releases, "ztunnel", "istio-system")


# ============================================================================
# SPIRE (--with-spire)
# ============================================================================


@pytest.mark.kind_only
class TestSpire:
    """Components installed by --with-spire."""

    def test_spire_crds_release(self, installed_flags, helm_releases):
        """spire-crds release deployed when --with-spire."""
        _skip_unless_flag(installed_flags, "spire")
        _assert_helm_release(helm_releases, "spire-crds", "spire-mgmt")

    def test_spire_release(self, installed_flags, helm_releases):
        """spire release deployed when --with-spire."""
        _skip_unless_flag(installed_flags, "spire")
        _assert_helm_release(helm_releases, "spire", "spire-mgmt")

    def test_spiffe_idp_job_completed(self, installed_flags, k8s_batch_client):
        """SPIFFE IdP setup job must have completed (Step 7)."""
        _skip_unless_flag(installed_flags, "spire")
        try:
            job = k8s_batch_client.read_namespaced_job(
                name="kagenti-spiffe-idp-setup-job", namespace="kagenti-system"
            )
        except ApiException:
            pytest.fail("kagenti-spiffe-idp-setup-job not found")

        succeeded = job.status.succeeded or 0
        assert succeeded >= 1, (
            f"SPIFFE IdP setup job not completed: succeeded={succeeded}, "
            f"failed={job.status.failed or 0}"
        )

    def test_spire_not_installed_without_flag(self, installed_flags, helm_releases):
        """SPIRE releases must NOT be deployed without --with-spire."""
        _skip_if_flag(installed_flags, "spire")
        _assert_no_helm_release(helm_releases, "spire-crds", "spire-mgmt")
        _assert_no_helm_release(helm_releases, "spire", "spire-mgmt")


# ============================================================================
# Backend (--with-backend)
# ============================================================================


@pytest.mark.kind_only
class TestBackend:
    """Components installed by --with-backend."""

    def test_backend_deployment_ready(self, installed_flags, k8s_apps_client):
        """kagenti-backend deployment must be ready when --with-backend."""
        _skip_unless_flag(installed_flags, "backend")
        _assert_deployment_ready(k8s_apps_client, "kagenti-backend", "kagenti-system")

    def test_backend_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """kagenti-backend must NOT be deployed without --with-backend."""
        _skip_if_flag(installed_flags, "backend")
        _assert_no_deployment(k8s_apps_client, "kagenti-backend", "kagenti-system")


# ============================================================================
# UI (--with-ui)
# ============================================================================


@pytest.mark.kind_only
class TestUI:
    """Components installed by --with-ui."""

    def test_ui_deployment_ready(self, installed_flags, k8s_apps_client):
        """kagenti-ui deployment must be ready when --with-ui."""
        _skip_unless_flag(installed_flags, "ui")
        _assert_deployment_ready(k8s_apps_client, "kagenti-ui", "kagenti-system")

    def test_backend_also_deployed(self, installed_flags, k8s_apps_client):
        """--with-ui must auto-enable --with-backend."""
        _skip_unless_flag(installed_flags, "ui")
        _assert_deployment_ready(k8s_apps_client, "kagenti-backend", "kagenti-system")

    def test_ui_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """kagenti-ui must NOT be deployed without --with-ui."""
        _skip_if_flag(installed_flags, "ui")
        _assert_no_deployment(k8s_apps_client, "kagenti-ui", "kagenti-system")


# ============================================================================
# OTel (--with-otel)
# ============================================================================


@pytest.mark.kind_only
class TestOTel:
    """Components installed by --with-otel."""

    def test_otel_collector_deployment_ready(self, installed_flags, k8s_apps_client):
        """otel-collector deployment must be ready when --with-otel."""
        _skip_unless_flag(installed_flags, "otel")
        _assert_deployment_ready(k8s_apps_client, "otel-collector", "kagenti-system")

    def test_otel_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """otel-collector must NOT be deployed without --with-otel."""
        _skip_if_flag(installed_flags, "otel")
        _assert_no_deployment(k8s_apps_client, "otel-collector", "kagenti-system")


# ============================================================================
# MLflow (--with-mlflow)
# ============================================================================


@pytest.mark.kind_only
class TestMLflow:
    """Components installed by --with-mlflow."""

    def test_mlflow_deployment_ready(self, installed_flags, k8s_apps_client):
        """mlflow deployment must be ready when --with-mlflow."""
        _skip_unless_flag(installed_flags, "mlflow")
        _assert_deployment_ready(k8s_apps_client, "mlflow", "kagenti-system")

    def test_mlflow_oauth_secret_exists(self, installed_flags, k8s_client):
        """mlflow-oauth-secret must exist when mlflow auth is enabled (created by Helm hook job)."""
        _skip_unless_flag(installed_flags, "mlflow")
        try:
            secret = k8s_client.read_namespaced_secret(
                name="mlflow-oauth-secret", namespace="kagenti-system"
            )
            assert secret.data, "mlflow-oauth-secret has no data"
        except ApiException as e:
            if e.status == 404:
                pytest.skip(
                    "mlflow-oauth-secret not found — MLflow auth may not be enabled"
                )
            pytest.fail(f"Unexpected error checking mlflow-oauth-secret: {e.reason}")

    def test_istio_ambient_also_deployed(self, installed_flags, helm_releases):
        """--with-mlflow must auto-enable --with-istio (waypoint dependency)."""
        _skip_unless_flag(installed_flags, "mlflow")
        _assert_helm_release(helm_releases, "istio-cni", "istio-system")
        _assert_helm_release(helm_releases, "ztunnel", "istio-system")

    def test_otel_also_deployed(self, installed_flags, k8s_apps_client):
        """--with-mlflow must auto-enable --with-otel (trace export)."""
        _skip_unless_flag(installed_flags, "mlflow")
        _assert_deployment_ready(k8s_apps_client, "otel-collector", "kagenti-system")

    def test_mlflow_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """mlflow must NOT be deployed without --with-mlflow."""
        _skip_if_flag(installed_flags, "mlflow")
        _assert_no_deployment(k8s_apps_client, "mlflow", "kagenti-system")


# ============================================================================
# Kiali (--with-kiali)
# ============================================================================


@pytest.mark.kind_only
class TestKiali:
    """Components installed by --with-kiali."""

    def test_kiali_deployment_ready(self, installed_flags, k8s_apps_client):
        """kiali deployment must be ready when --with-kiali."""
        _skip_unless_flag(installed_flags, "kiali")
        _assert_deployment_ready(k8s_apps_client, "kiali", "istio-system")

    def test_prometheus_deployment_ready(self, installed_flags, k8s_apps_client):
        """prometheus deployment must be ready when --with-kiali."""
        _skip_unless_flag(installed_flags, "kiali")
        _assert_deployment_ready(k8s_apps_client, "prometheus", "istio-system")

    def test_istio_ambient_also_deployed(self, installed_flags, helm_releases):
        """--with-kiali must auto-enable --with-istio."""
        _skip_unless_flag(installed_flags, "kiali")
        _assert_helm_release(helm_releases, "istio-cni", "istio-system")
        _assert_helm_release(helm_releases, "ztunnel", "istio-system")

    def test_kiali_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """kiali must NOT be deployed without --with-kiali."""
        _skip_if_flag(installed_flags, "kiali")
        _assert_no_deployment(k8s_apps_client, "kiali", "istio-system")


# ============================================================================
# Builds (--with-builds)
# ============================================================================


@pytest.mark.kind_only
class TestBuilds:
    """Components installed by --with-builds (Tekton + Shipwright + Registry)."""

    def test_tekton_controller_ready(self, installed_flags, k8s_apps_client):
        """Tekton pipeline controller must be ready when --with-builds."""
        _skip_unless_flag(installed_flags, "builds")
        _assert_deployment_ready(
            k8s_apps_client, "tekton-pipelines-controller", "tekton-pipelines"
        )

    def test_container_registry_ready(self, installed_flags, k8s_apps_client):
        """Container registry must be ready when --with-builds."""
        _skip_unless_flag(installed_flags, "builds")
        _assert_deployment_ready(k8s_apps_client, "registry", "cr-system")

    def test_shipwright_controller_ready(self, installed_flags, k8s_apps_client):
        """Shipwright build controller must be ready when --with-builds."""
        _skip_unless_flag(installed_flags, "builds")
        _assert_deployment_ready(
            k8s_apps_client, "shipwright-build-controller", "shipwright-build"
        )

    def test_builds_not_installed_without_flag(self, installed_flags, k8s_apps_client):
        """Tekton must NOT be deployed without --with-builds."""
        _skip_if_flag(installed_flags, "builds")
        _assert_no_deployment(
            k8s_apps_client, "tekton-pipelines-controller", "tekton-pipelines"
        )


# ============================================================================
# MCP Gateway (--with-mcp-gateway)
# ============================================================================


@pytest.mark.kind_only
class TestMCPGateway:
    """Components installed by --with-mcp-gateway."""

    def test_mcp_gateway_release(self, installed_flags, helm_releases):
        """mcp-gateway Helm release must be deployed when --with-mcp-gateway."""
        _skip_unless_flag(installed_flags, "mcp_gateway")
        _assert_helm_release(helm_releases, "mcp-gateway", "mcp-system")

    def test_mcp_gateway_not_installed_without_flag(
        self, installed_flags, helm_releases
    ):
        """mcp-gateway must NOT be deployed without --with-mcp-gateway."""
        _skip_if_flag(installed_flags, "mcp_gateway")
        _assert_no_helm_release(helm_releases, "mcp-gateway", "mcp-system")


# ============================================================================
# Kuadrant (--with-kuadrant)
# ============================================================================


@pytest.mark.kind_only
class TestKuadrant:
    """Components installed by --with-kuadrant."""

    def test_kuadrant_release(self, installed_flags, helm_releases):
        """kuadrant-operator Helm release must be deployed when --with-kuadrant."""
        _skip_unless_flag(installed_flags, "kuadrant")
        _assert_helm_release(helm_releases, "kuadrant-operator", "kuadrant-system")

    def test_mcp_gateway_also_deployed(self, installed_flags, helm_releases):
        """--with-kuadrant must auto-enable --with-mcp-gateway."""
        _skip_unless_flag(installed_flags, "kuadrant")
        _assert_helm_release(helm_releases, "mcp-gateway", "mcp-system")

    def test_kuadrant_not_installed_without_flag(self, installed_flags, helm_releases):
        """kuadrant must NOT be deployed without --with-kuadrant."""
        _skip_if_flag(installed_flags, "kuadrant")
        _assert_no_helm_release(helm_releases, "kuadrant-operator", "kuadrant-system")


# ============================================================================
# Flag Dependency Verification (cross-cutting)
# ============================================================================


@pytest.mark.kind_only
class TestFlagDependencies:
    """Verify --with-* flag dependency auto-enable behavior."""

    def test_with_ui_enables_backend(self, installed_flags, k8s_apps_client):
        """When --with-ui is set, backend must also be deployed."""
        _skip_unless_flag(installed_flags, "ui")
        assert "backend" in installed_flags or _deployment_exists(
            k8s_apps_client, "kagenti-backend", "kagenti-system"
        ), "--with-ui should auto-enable --with-backend"

    def test_with_kiali_enables_istio(self, installed_flags, helm_releases):
        """When --with-kiali is set, Istio ambient must also be deployed."""
        _skip_unless_flag(installed_flags, "kiali")
        _assert_helm_release(helm_releases, "istio-cni", "istio-system")

    def test_with_mlflow_enables_istio_and_otel(
        self, installed_flags, helm_releases, k8s_apps_client
    ):
        """When --with-mlflow is set, Istio ambient and OTel must also be deployed."""
        _skip_unless_flag(installed_flags, "mlflow")
        _assert_helm_release(helm_releases, "istio-cni", "istio-system")
        _assert_deployment_ready(k8s_apps_client, "otel-collector", "kagenti-system")

    def test_with_kuadrant_enables_mcp_gateway(self, installed_flags, helm_releases):
        """When --with-kuadrant is set, MCP Gateway must also be deployed."""
        _skip_unless_flag(installed_flags, "kuadrant")
        _assert_helm_release(helm_releases, "mcp-gateway", "mcp-system")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
