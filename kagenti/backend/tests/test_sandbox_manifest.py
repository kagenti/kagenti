# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for Sandbox manifest builder and Service creation."""

from unittest.mock import MagicMock

from app.core.constants import DEFAULT_IN_CLUSTER_PORT, DEFAULT_OFF_CLUSTER_PORT
from app.routers.agents import CreateAgentRequest, PersistentStorageConfig, WORKLOAD_TYPE_SANDBOX


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
    req.persistentStorage = overrides.get("persistentStorage", None)
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

    def test_service_false_in_spec(self):
        """Sandbox spec sets service: false to prevent agent-sandbox controller
        from creating a conflicting headless Service (v0.4.6+ opt-in behavior)."""
        from app.routers.agents import _build_sandbox_manifest

        request = _make_request()
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        assert manifest["spec"]["service"] is False

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


class TestBuildSandboxManifestPVC:
    """Tests for PVC support in _build_sandbox_manifest."""

    def test_no_pvc_by_default(self):
        """No volumeClaimTemplates when persistentStorage is None."""
        from app.routers.agents import _build_sandbox_manifest

        request = _make_request()
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        assert "volumeClaimTemplates" not in manifest["spec"]
        volume_names = [v["name"] for v in manifest["spec"]["podTemplate"]["spec"]["volumes"]]
        assert "shared-data" in volume_names

    def test_pvc_when_enabled(self):
        """volumeClaimTemplates present with correct size when persistentStorage enabled."""
        from app.routers.agents import _build_sandbox_manifest

        storage = PersistentStorageConfig(enabled=True, size="5Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        vct = manifest["spec"]["volumeClaimTemplates"]
        assert len(vct) == 1
        assert vct[0]["metadata"]["name"] == "shared-data"
        assert vct[0]["metadata"]["labels"]["app.kubernetes.io/name"] == "test-agent"
        assert vct[0]["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert vct[0]["spec"]["resources"]["requests"]["storage"] == "5Gi"

    def test_pvc_replaces_shared_data_emptydir(self):
        """shared-data emptyDir is removed from volumes when PVC is enabled."""
        from app.routers.agents import _build_sandbox_manifest

        storage = PersistentStorageConfig(enabled=True, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        volume_names = [v["name"] for v in manifest["spec"]["podTemplate"]["spec"]["volumes"]]
        assert "shared-data" not in volume_names
        assert "cache" in volume_names
        assert "marvin" in volume_names

    def test_pvc_volume_mount_unchanged(self):
        """/shared mount is present regardless of PVC enablement."""
        from app.routers.agents import _build_sandbox_manifest

        storage = PersistentStorageConfig(enabled=True, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        container = manifest["spec"]["podTemplate"]["spec"]["containers"][0]
        mount_names = [m["name"] for m in container["volumeMounts"]]
        assert "shared-data" in mount_names
        mount = next(m for m in container["volumeMounts"] if m["name"] == "shared-data")
        assert mount["mountPath"] == "/shared"

    def test_pvc_disabled_keeps_emptydir(self):
        """When persistentStorage.enabled is False, shared-data stays as emptyDir."""
        from app.routers.agents import _build_sandbox_manifest

        storage = PersistentStorageConfig(enabled=False, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        assert "volumeClaimTemplates" not in manifest["spec"]
        volume_names = [v["name"] for v in manifest["spec"]["podTemplate"]["spec"]["volumes"]]
        assert "shared-data" in volume_names

    def test_pvc_default_size(self):
        """Default PVC size is 1Gi."""
        from app.routers.agents import _build_sandbox_manifest

        storage = PersistentStorageConfig(enabled=True)
        request = _make_request(persistentStorage=storage)
        manifest = _build_sandbox_manifest(request=request, image="test:latest")

        vct = manifest["spec"]["volumeClaimTemplates"]
        assert vct[0]["spec"]["resources"]["requests"]["storage"] == "1Gi"


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
    flow. Covers the workload-type gate (Job → skip, others → create)."""

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
        """Sandbox agents get a backend-managed ClusterIP Service for port
        translation (8080→8000). The agent-sandbox controller's headless
        Service is suppressed via spec.service: false on the Sandbox CR."""
        from app.routers.agents import _create_or_replace_service

        kube = MagicMock()
        manifest = self._service_manifest("sb")
        _create_or_replace_service(kube, "team1", "sb", manifest, WORKLOAD_TYPE_SANDBOX)

        kube.create_service.assert_called_once_with(namespace="team1", body=manifest)

    def test_deployment_creates_service(self):
        """Deployment workloads always get a Service — the most common path."""
        from app.routers.agents import _create_or_replace_service

        kube = MagicMock()
        manifest = self._service_manifest("dep")
        _create_or_replace_service(kube, "team1", "dep", manifest, "deployment")

        kube.create_service.assert_called_once_with(namespace="team1", body=manifest)
        kube.delete_service.assert_not_called()

    def test_sandbox_409_propagates(self):
        """Sandbox workloads now create a Service — a 409 is a real conflict
        and must propagate (same as Deployment workloads)."""
        from app.routers.agents import _create_or_replace_service
        from kubernetes.client import ApiException
        import pytest

        kube = MagicMock()
        kube.create_service.side_effect = ApiException(status=409)
        manifest = self._service_manifest("sb")

        with pytest.raises(ApiException):
            _create_or_replace_service(kube, "team1", "sb", manifest, WORKLOAD_TYPE_SANDBOX)

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

    def test_non_409_propagates_for_deployment(self):
        """Non-409 errors propagate for Deployment workloads so callers can
        see real failures (403, 500, etc.)."""
        from app.routers.agents import _create_or_replace_service
        from kubernetes.client import ApiException
        import pytest

        kube = MagicMock()
        kube.create_service.side_effect = ApiException(status=500)

        with pytest.raises(ApiException) as exc_info:
            _create_or_replace_service(
                kube, "team1", "dep", self._service_manifest("dep"), "deployment"
            )
        assert exc_info.value.status == 500
        kube.delete_service.assert_not_called()
