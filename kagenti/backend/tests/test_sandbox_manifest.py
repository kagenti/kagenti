# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for Sandbox manifest builder and Service creation."""

from unittest.mock import MagicMock

from app.core.constants import DEFAULT_IN_CLUSTER_PORT, DEFAULT_OFF_CLUSTER_PORT
from app.routers.agents import CreateAgentRequest, WORKLOAD_TYPE_SANDBOX


def _make_request(**overrides):
    """Build a minimal CreateAgentRequest-like object for testing."""
    req = MagicMock(spec=CreateAgentRequest)
    req.name = overrides.get("name", "test-agent")
    req.namespace = overrides.get("namespace", "team1")
    req.containerImage = overrides.get("containerImage", "ghcr.io/example/agent:latest")
    req.framework = overrides.get("framework", "langgraph")
    req.protocol = overrides.get("protocol", "a2a")
    req.workloadType = overrides.get("workloadType", "sandbox")
    req.servicePorts = overrides.get("servicePorts", None)
    req.envVars = overrides.get("envVars", None)
    req.imagePullSecret = overrides.get("imagePullSecret", None)
    req.authBridgeEnabled = overrides.get("authBridgeEnabled", False)
    req.spireEnabled = overrides.get("spireEnabled", False)
    req.envoyProxyInject = overrides.get("envoyProxyInject", None)
    req.spiffeHelperInject = overrides.get("spiffeHelperInject", None)
    req.clientRegistrationInject = overrides.get("clientRegistrationInject", None)
    req.outboundPortsExclude = overrides.get("outboundPortsExclude", None)
    req.inboundPortsExclude = overrides.get("inboundPortsExclude", None)
    req.outboundRoutes = overrides.get("outboundRoutes", None)
    req.defaultOutboundPolicy = overrides.get("defaultOutboundPolicy", None)
    return req


class TestBuildSandboxManifest:
    """Tests for _build_sandbox_manifest."""

    def test_default_container_port_is_in_cluster_port(self):
        """Sandbox containerPort defaults to DEFAULT_IN_CLUSTER_PORT (8000), same as Deployment."""
        from app.routers.agents import _build_sandbox_manifest

        request = _make_request()
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        container = manifest["spec"]["podTemplate"]["spec"]["containers"][0]
        assert container["ports"][0]["containerPort"] == DEFAULT_IN_CLUSTER_PORT

    def test_port_env_var_is_in_cluster_port(self):
        """PORT env var defaults to DEFAULT_IN_CLUSTER_PORT (8000), not the service port."""
        from app.routers.agents import _build_sandbox_manifest

        request = _make_request()
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        container = manifest["spec"]["podTemplate"]["spec"]["containers"][0]
        port_env = next(ev for ev in container["env"] if ev.get("name") == "PORT")
        assert port_env["value"] == str(DEFAULT_IN_CLUSTER_PORT)

    def test_no_service_field_in_spec(self):
        """Sandbox spec must NOT include a service field (unsupported in released CRD)."""
        from app.routers.agents import _build_sandbox_manifest

        request = _make_request()
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        assert "service" not in manifest["spec"]

    def test_custom_service_ports_override_container_port(self):
        """When servicePorts are provided, containerPort uses targetPort from first entry."""
        from app.routers.agents import _build_sandbox_manifest

        sp = MagicMock()
        sp.name = "http"
        sp.port = 9090
        sp.targetPort = 8888
        sp.protocol = "TCP"
        request = _make_request(servicePorts=[sp])
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        container = manifest["spec"]["podTemplate"]["spec"]["containers"][0]
        assert container["ports"][0]["containerPort"] == 8888


class TestBuildServiceManifestForSandbox:
    """Tests for _build_service_manifest when used with Sandbox workloads."""

    def test_default_service_ports(self):
        """Service defaults to port 8080 -> targetPort 8000."""
        from app.routers.agents import _build_service_manifest

        request = _make_request()
        manifest = _build_service_manifest(request)

        ports = manifest["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0]["port"] == DEFAULT_OFF_CLUSTER_PORT
        assert ports[0]["targetPort"] == DEFAULT_IN_CLUSTER_PORT

    def test_service_labels_use_request_workload_type(self):
        """Service labels should reflect the actual workload type, not hardcoded deployment."""
        from app.routers.agents import _build_service_manifest

        request = _make_request(workloadType="sandbox")
        manifest = _build_service_manifest(request)

        labels = manifest["metadata"]["labels"]
        assert labels.get("kagenti.io/workload-type") == "sandbox"


class TestCreateOrReplaceService:
    """Tests for `_create_or_replace_service` — the shared helper used by both
    the image-based agent-create flow and the source-build / Shipwright finalize
    flow. Covers the workload-type gate (Job → skip) and the Sandbox controller
    409-race recovery (delete+recreate). Pre-`kagenti#1581` / `#1593` the two
    call sites had divergent inline copies of this logic; the helper exists to
    keep them from drifting again, and these tests pin the contract."""

    def _service_manifest(self, name="test-agent"):
        # The helper doesn't inspect the manifest content, just passes it
        # through to create_service / delete_service. A minimal stub is fine.
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": "team1", "labels": {}},
            "spec": {"selector": {}, "ports": []},
        }

    def test_job_workload_skips_service_creation(self):
        """Jobs don't get a Service — `kube.create_service` must not be called."""
        from app.routers.agents import _create_or_replace_service, WORKLOAD_TYPE_JOB

        kube = MagicMock()
        _create_or_replace_service(
            kube, "team1", "j", self._service_manifest("j"), WORKLOAD_TYPE_JOB
        )

        kube.create_service.assert_not_called()
        kube.delete_service.assert_not_called()

    def test_sandbox_creates_service(self):
        """Sandbox must NOT be skipped — pre-`kagenti#1581` it was, breaking the
        operator's AgentCardReconciler. This test would have caught both that
        regression and the source-build path's parallel bug fixed by `#1593`."""
        from app.routers.agents import _create_or_replace_service

        kube = MagicMock()
        manifest = self._service_manifest("sb")
        _create_or_replace_service(kube, "team1", "sb", manifest, WORKLOAD_TYPE_SANDBOX)

        kube.create_service.assert_called_once_with(namespace="team1", body=manifest)
        kube.delete_service.assert_not_called()

    def test_deployment_creates_service(self):
        """Deployment workloads always get a Service — the most common path."""
        from app.routers.agents import _create_or_replace_service

        kube = MagicMock()
        manifest = self._service_manifest("dep")
        _create_or_replace_service(kube, "team1", "dep", manifest, "deployment")

        kube.create_service.assert_called_once_with(namespace="team1", body=manifest)
        kube.delete_service.assert_not_called()

    def test_sandbox_409_replaces_existing_service(self):
        """The agent-sandbox controller can race us by creating its own
        short-lived Service. On 409 we delete it and recreate with our
        backend-managed shape (kagenti#1581's pattern)."""
        from app.routers.agents import _create_or_replace_service
        from kubernetes.client import ApiException

        kube = MagicMock()
        # First create_service raises 409; second succeeds (after delete).
        kube.create_service.side_effect = [ApiException(status=409), None]
        manifest = self._service_manifest("sb")

        _create_or_replace_service(kube, "team1", "sb", manifest, WORKLOAD_TYPE_SANDBOX)

        assert kube.create_service.call_count == 2
        kube.delete_service.assert_called_once_with(namespace="team1", name="sb")

    def test_deployment_409_propagates(self):
        """Deployment workloads do not have a controller-race recovery — a 409
        is a real conflict (e.g., user re-importing on top of an existing
        Service) and must propagate so the API caller sees a clear error."""
        from app.routers.agents import _create_or_replace_service
        from kubernetes.client import ApiException
        import pytest

        kube = MagicMock()
        kube.create_service.side_effect = ApiException(status=409)

        with pytest.raises(ApiException) as exc_info:
            _create_or_replace_service(
                kube, "team1", "dep", self._service_manifest("dep"), "deployment"
            )
        assert exc_info.value.status == 409
        kube.delete_service.assert_not_called()

    def test_non_409_propagates_for_sandbox(self):
        """Even on Sandbox, only a 409 triggers the replace path. Other API
        errors (403, 500, etc.) propagate so callers can see real failures."""
        from app.routers.agents import _create_or_replace_service
        from kubernetes.client import ApiException
        import pytest

        kube = MagicMock()
        kube.create_service.side_effect = ApiException(status=500)

        with pytest.raises(ApiException) as exc_info:
            _create_or_replace_service(
                kube, "team1", "sb", self._service_manifest("sb"), WORKLOAD_TYPE_SANDBOX
            )
        assert exc_info.value.status == 500
        kube.delete_service.assert_not_called()
