# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for Sandbox manifest builder and Service creation."""

from unittest.mock import MagicMock

from app.core.constants import DEFAULT_IN_CLUSTER_PORT, DEFAULT_OFF_CLUSTER_PORT


def _make_request(**overrides):
    """Build a minimal CreateAgentRequest-like object for testing."""
    req = MagicMock()
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

    def test_service_disabled(self):
        """Sandbox spec must set service: false to disable auto-generated headless Service."""
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
