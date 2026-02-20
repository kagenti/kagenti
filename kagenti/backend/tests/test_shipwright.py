# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for Shipwright build functionality.

Tests cover:
- Build manifest generation for various scenarios
- BuildRun manifest generation
- Build strategy selection logic
- Agent config annotation storage
"""

import json
import pytest

from app.routers.agents import (
    CreateAgentRequest,
    ShipwrightBuildConfig,
    EnvVar,
    ServicePort,
    _build_agent_shipwright_build_manifest,
    _build_agent_shipwright_buildrun_manifest,
)
from app.core.constants import (
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_STRATEGY_INSECURE,
    SHIPWRIGHT_STRATEGY_SECURE,
    DEFAULT_INTERNAL_REGISTRY,
    SHIPWRIGHT_GIT_SECRET_NAME,
    SHIPWRIGHT_DEFAULT_DOCKERFILE,
    SHIPWRIGHT_DEFAULT_TIMEOUT,
    SHIPWRIGHT_DEFAULT_RETENTION_SUCCEEDED,
    SHIPWRIGHT_DEFAULT_RETENTION_FAILED,
    KAGENTI_TYPE_LABEL,
    KAGENTI_PROTOCOL_LABEL,
    KAGENTI_FRAMEWORK_LABEL,
    RESOURCE_TYPE_AGENT,
)


class TestBuildShipwrightBuildManifest:
    """Tests for _build_agent_shipwright_build_manifest function."""

    def test_basic_build_manifest_with_internal_registry(self):
        """Test basic build manifest generation for internal registry."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Check API version and kind
        assert manifest["apiVersion"] == f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}"
        assert manifest["kind"] == "Build"

        # Check metadata
        assert manifest["metadata"]["name"] == "test-agent"
        assert manifest["metadata"]["namespace"] == "team1"
        assert manifest["metadata"]["labels"][KAGENTI_TYPE_LABEL] == RESOURCE_TYPE_AGENT
        assert manifest["metadata"]["labels"][KAGENTI_PROTOCOL_LABEL] == "a2a"
        assert manifest["metadata"]["labels"][KAGENTI_FRAMEWORK_LABEL] == "LangGraph"

        # Check source configuration
        assert manifest["spec"]["source"]["type"] == "Git"
        assert manifest["spec"]["source"]["git"]["url"] == "https://github.com/example/repo"
        assert manifest["spec"]["source"]["git"]["revision"] == "main"
        # No clone_secret_name passed, so cloneSecret should be absent
        assert "cloneSecret" not in manifest["spec"]["source"]["git"]
        assert manifest["spec"]["source"]["contextDir"] == "agents/test"

    def test_build_manifest_with_clone_secret(self):
        """Test that cloneSecret is included when clone_secret_name is provided."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
        )

        manifest = _build_agent_shipwright_build_manifest(
            request, clone_secret_name=SHIPWRIGHT_GIT_SECRET_NAME
        )
        assert manifest["spec"]["source"]["git"]["cloneSecret"] == SHIPWRIGHT_GIT_SECRET_NAME

    def test_build_manifest_without_clone_secret(self):
        """Test that cloneSecret is omitted when no clone_secret_name is provided."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/public-repo",
            gitPath=".",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
        )

        manifest = _build_agent_shipwright_build_manifest(request)
        assert "cloneSecret" not in manifest["spec"]["source"]["git"]

        # Check strategy - should be insecure for internal registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE
        assert manifest["spec"]["strategy"]["kind"] == "ClusterBuildStrategy"

        # Check output
        expected_image = f"{DEFAULT_INTERNAL_REGISTRY}/test-agent:v0.0.1"
        assert manifest["spec"]["output"]["image"] == expected_image

        # Check defaults
        assert manifest["spec"]["timeout"] == SHIPWRIGHT_DEFAULT_TIMEOUT
        assert (
            manifest["spec"]["retention"]["succeededLimit"]
            == SHIPWRIGHT_DEFAULT_RETENTION_SUCCEEDED
        )
        assert manifest["spec"]["retention"]["failedLimit"] == SHIPWRIGHT_DEFAULT_RETENTION_FAILED

    def test_build_manifest_with_external_registry(self):
        """Test build manifest generation for external registry (quay.io)."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            registryUrl="quay.io/myorg",
            registrySecret="quay-credentials",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_SECURE,
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Check strategy - should be secure for external registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_SECURE

        # Check output image and push secret
        assert manifest["spec"]["output"]["image"] == "quay.io/myorg/test-agent:v0.0.1"
        assert manifest["spec"]["output"]["pushSecret"] == "quay-credentials"

    def test_build_manifest_strategy_override_for_internal_registry(self):
        """Test that secure strategy is overridden to insecure for internal registry."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            # Using default internal registry
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_SECURE,  # This should be overridden
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Should be overridden to insecure for internal registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE

    def test_build_manifest_with_custom_registry_containing_cluster_local(self):
        """Test that registries containing svc.cluster.local use insecure strategy."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            registryUrl="my-registry.svc.cluster.local:5000",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_SECURE,
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Should be overridden to insecure for cluster-local registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE

    def test_build_manifest_with_custom_dockerfile(self):
        """Test build manifest with custom Dockerfile path."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            shipwrightConfig=ShipwrightBuildConfig(
                dockerfile="docker/Dockerfile.prod",
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Check dockerfile param
        dockerfile_param = next(
            (p for p in manifest["spec"]["paramValues"] if p["name"] == "dockerfile"),
            None,
        )
        assert dockerfile_param is not None
        assert dockerfile_param["value"] == "docker/Dockerfile.prod"

    def test_build_manifest_with_build_args(self):
        """Test build manifest with build arguments."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            shipwrightConfig=ShipwrightBuildConfig(
                buildArgs=["PYTHON_VERSION=3.11", "DEBUG=false"],
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Check build-args param
        build_args_param = next(
            (p for p in manifest["spec"]["paramValues"] if p["name"] == "build-args"),
            None,
        )
        assert build_args_param is not None
        assert len(build_args_param["values"]) == 2
        assert build_args_param["values"][0]["value"] == "PYTHON_VERSION=3.11"
        assert build_args_param["values"][1]["value"] == "DEBUG=false"

    def test_build_manifest_with_custom_timeout(self):
        """Test build manifest with custom timeout."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            shipwrightConfig=ShipwrightBuildConfig(
                buildTimeout="30m",
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        assert manifest["spec"]["timeout"] == "30m"

    def test_build_manifest_stores_agent_config_in_annotations(self):
        """Test that agent configuration is stored in Build annotations."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="CrewAI",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            createHttpRoute=True,
            registrySecret="my-secret",
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Check annotation exists
        assert "kagenti.io/agent-config" in manifest["metadata"]["annotations"]

        # Parse and verify stored config
        stored_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/agent-config"])
        assert stored_config["protocol"] == "a2a"
        assert stored_config["framework"] == "CrewAI"
        assert stored_config["createHttpRoute"] is True
        assert stored_config["registrySecret"] == "my-secret"

    def test_build_manifest_stores_env_vars_in_annotations(self):
        """Test that environment variables are stored in Build annotations."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            envVars=[
                EnvVar(name="API_KEY", value="secret123"),
                EnvVar(name="DEBUG", value="true"),
            ],
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        stored_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/agent-config"])
        assert "envVars" in stored_config
        assert len(stored_config["envVars"]) == 2
        assert stored_config["envVars"][0]["name"] == "API_KEY"
        assert stored_config["envVars"][0]["value"] == "secret123"

    def test_build_manifest_stores_service_ports_in_annotations(self):
        """Test that service ports are stored in Build annotations."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            servicePorts=[
                ServicePort(name="http", port=8080, targetPort=8000, protocol="TCP"),
                ServicePort(name="grpc", port=9090, targetPort=9000, protocol="TCP"),
            ],
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        stored_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/agent-config"])
        assert "servicePorts" in stored_config
        assert len(stored_config["servicePorts"]) == 2
        assert stored_config["servicePorts"][0]["name"] == "http"
        assert stored_config["servicePorts"][0]["port"] == 8080

    def test_build_manifest_with_empty_git_path(self):
        """Test build manifest when gitPath is empty (root directory)."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="",  # Empty path
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Should default to "."
        assert manifest["spec"]["source"]["contextDir"] == "."


class TestBuildShipwrightBuildRunManifest:
    """Tests for _build_agent_shipwright_buildrun_manifest function."""

    def test_basic_buildrun_manifest(self):
        """Test basic BuildRun manifest generation."""
        manifest = _build_agent_shipwright_buildrun_manifest(
            build_name="test-agent",
            namespace="team1",
        )

        # Check API version and kind
        assert manifest["apiVersion"] == f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}"
        assert manifest["kind"] == "BuildRun"

        # Check metadata
        assert manifest["metadata"]["generateName"] == "test-agent-run-"
        assert manifest["metadata"]["namespace"] == "team1"

        # Check labels
        assert manifest["metadata"]["labels"]["kagenti.io/build-name"] == "test-agent"
        assert "app.kubernetes.io/created-by" in manifest["metadata"]["labels"]

        # Check spec
        assert manifest["spec"]["build"]["name"] == "test-agent"

    def test_buildrun_manifest_with_additional_labels(self):
        """Test BuildRun manifest with additional labels passed through."""
        additional_labels = {
            "kagenti.io/type": "agent",
            "kagenti.io/protocol": "a2a",
            "custom-label": "custom-value",
        }

        manifest = _build_agent_shipwright_buildrun_manifest(
            build_name="test-agent",
            namespace="team1",
            labels=additional_labels,
        )

        # Check that additional labels are merged
        assert manifest["metadata"]["labels"]["kagenti.io/type"] == "agent"
        assert manifest["metadata"]["labels"]["kagenti.io/protocol"] == "a2a"
        assert manifest["metadata"]["labels"]["custom-label"] == "custom-value"

        # Check that base labels are preserved
        assert manifest["metadata"]["labels"]["kagenti.io/build-name"] == "test-agent"

    def test_buildrun_manifest_labels_override(self):
        """Test that passed labels can override base labels."""
        additional_labels = {
            "kagenti.io/build-name": "overridden-name",  # This will override
        }

        manifest = _build_agent_shipwright_buildrun_manifest(
            build_name="test-agent",
            namespace="team1",
            labels=additional_labels,
        )

        # The additional labels are merged after base labels, so they override
        assert manifest["metadata"]["labels"]["kagenti.io/build-name"] == "overridden-name"


class TestBuildStrategySelection:
    """Tests for build strategy selection logic."""

    def test_default_strategy_for_internal_registry(self):
        """Test that internal registry defaults to insecure strategy."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            # No registry specified = internal registry
        )

        manifest = _build_agent_shipwright_build_manifest(request)
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE

    def test_insecure_strategy_preserved_for_external_registry(self):
        """Test that explicit insecure strategy is preserved for external registry."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            registryUrl="quay.io/myorg",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_INSECURE,  # Explicit insecure
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)

        # Insecure strategy is preserved even for external registry
        # (user explicitly chose it)
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE

    def test_secure_strategy_for_external_registry(self):
        """Test that secure strategy is used for external registry."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            registryUrl="ghcr.io/myorg",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_SECURE,
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_SECURE

    def test_docker_hub_registry(self):
        """Test strategy for Docker Hub registry."""
        request = CreateAgentRequest(
            name="test-agent",
            namespace="team1",
            protocol="a2a",
            framework="LangGraph",
            gitUrl="https://github.com/example/repo",
            gitPath="agents/test",
            gitBranch="main",
            imageTag="v0.0.1",
            deploymentMethod="source",
            registryUrl="docker.io/myorg",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy=SHIPWRIGHT_STRATEGY_SECURE,
            ),
        )

        manifest = _build_agent_shipwright_build_manifest(request)
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_SECURE


class TestShipwrightBuildConfig:
    """Tests for ShipwrightBuildConfig model."""

    def test_default_values(self):
        """Test default values for ShipwrightBuildConfig."""
        config = ShipwrightBuildConfig()

        # buildStrategy defaults to None to allow automatic selection based on registry type
        assert config.buildStrategy is None
        assert config.dockerfile == SHIPWRIGHT_DEFAULT_DOCKERFILE
        assert config.buildArgs is None
        assert config.buildTimeout == SHIPWRIGHT_DEFAULT_TIMEOUT

    def test_custom_values(self):
        """Test custom values for ShipwrightBuildConfig."""
        config = ShipwrightBuildConfig(
            buildStrategy="buildah",
            dockerfile="Dockerfile.custom",
            buildArgs=["ARG1=val1", "ARG2=val2"],
            buildTimeout="30m",
        )

        assert config.buildStrategy == "buildah"
        assert config.dockerfile == "Dockerfile.custom"
        assert config.buildArgs == ["ARG1=val1", "ARG2=val2"]
        assert config.buildTimeout == "30m"


class TestBuildRunPhaseDetection:
    """Tests for BuildRun phase detection logic.

    These tests verify the logic for determining BuildRun phase from conditions.
    The actual implementation is in the endpoint, but we test the logic pattern here.
    """

    def _determine_phase(self, conditions: list) -> tuple:
        """Helper to mimic phase detection logic from the endpoint."""
        phase = "Pending"
        failure_message = None

        for cond in conditions:
            if cond.get("type") == "Succeeded":
                if cond.get("status") == "True":
                    phase = "Succeeded"
                elif cond.get("status") == "False":
                    phase = "Failed"
                    failure_message = cond.get("message")
                else:
                    phase = "Running"
                break

        return phase, failure_message

    def test_phase_pending_no_conditions(self):
        """Test that empty conditions result in Pending phase."""
        phase, failure_message = self._determine_phase([])
        assert phase == "Pending"
        assert failure_message is None

    def test_phase_running(self):
        """Test that Unknown Succeeded status results in Running phase."""
        conditions = [{"type": "Succeeded", "status": "Unknown", "reason": "Running"}]
        phase, failure_message = self._determine_phase(conditions)
        assert phase == "Running"
        assert failure_message is None

    def test_phase_succeeded(self):
        """Test that True Succeeded status results in Succeeded phase."""
        conditions = [{"type": "Succeeded", "status": "True", "reason": "Succeeded"}]
        phase, failure_message = self._determine_phase(conditions)
        assert phase == "Succeeded"
        assert failure_message is None

    def test_phase_failed(self):
        """Test that False Succeeded status results in Failed phase."""
        conditions = [
            {
                "type": "Succeeded",
                "status": "False",
                "reason": "BuildFailed",
                "message": "Dockerfile not found",
            }
        ]
        phase, failure_message = self._determine_phase(conditions)
        assert phase == "Failed"
        assert failure_message == "Dockerfile not found"

    def test_phase_ignores_other_conditions(self):
        """Test that non-Succeeded conditions are ignored for phase detection."""
        conditions = [
            {"type": "Ready", "status": "True"},
            {"type": "Running", "status": "True"},
        ]
        phase, failure_message = self._determine_phase(conditions)
        # Without Succeeded condition, defaults to Pending
        assert phase == "Pending"

    def test_phase_multiple_conditions(self):
        """Test phase detection with multiple conditions."""
        conditions = [
            {"type": "Ready", "status": "True"},
            {"type": "Succeeded", "status": "True", "reason": "Succeeded"},
            {"type": "Running", "status": "False"},
        ]
        phase, failure_message = self._determine_phase(conditions)
        assert phase == "Succeeded"


class TestResourceConfigFromBuild:
    """Tests for parsing resource config from Build annotations."""

    def test_parse_basic_config(self):
        """Test parsing basic resource config."""
        from app.models.shipwright import ResourceConfigFromBuild

        config_dict = {
            "protocol": "a2a",
            "framework": "LangGraph",
            "createHttpRoute": True,
            "registrySecret": "my-secret",
        }

        config = ResourceConfigFromBuild(**config_dict)

        assert config.protocol == "a2a"
        assert config.framework == "LangGraph"
        assert config.createHttpRoute is True
        assert config.registrySecret == "my-secret"

    def test_parse_config_with_env_vars(self):
        """Test parsing config with environment variables."""
        from app.models.shipwright import ResourceConfigFromBuild

        config_dict = {
            "protocol": "a2a",
            "framework": "LangGraph",
            "createHttpRoute": False,
            "envVars": [
                {"name": "API_KEY", "value": "secret"},
                {"name": "DEBUG", "value": "true"},
            ],
        }

        config = ResourceConfigFromBuild(**config_dict)

        assert config.envVars is not None
        assert len(config.envVars) == 2
        assert config.envVars[0]["name"] == "API_KEY"

    def test_parse_config_with_service_ports(self):
        """Test parsing config with service ports."""
        from app.models.shipwright import ResourceConfigFromBuild

        config_dict = {
            "protocol": "a2a",
            "framework": "LangGraph",
            "createHttpRoute": True,
            "servicePorts": [
                {"name": "http", "port": 8080, "targetPort": 8000, "protocol": "TCP"},
            ],
        }

        config = ResourceConfigFromBuild(**config_dict)

        assert config.servicePorts is not None
        assert len(config.servicePorts) == 1
        assert config.servicePorts[0]["port"] == 8080

    def test_parse_config_minimal(self):
        """Test parsing minimal config with only required fields."""
        from app.models.shipwright import ResourceConfigFromBuild

        config_dict = {
            "protocol": "mcp",
            "framework": "Python",
            "createHttpRoute": False,
        }

        config = ResourceConfigFromBuild(**config_dict)

        assert config.protocol == "mcp"
        assert config.framework == "Python"
        assert config.createHttpRoute is False
        assert config.registrySecret is None
        assert config.envVars is None
        assert config.servicePorts is None


class TestShipwrightBuildInfoResponse:
    """Tests for ShipwrightBuildInfoResponse model."""

    def test_response_without_buildrun(self):
        """Test response when no BuildRun exists."""
        from app.models.shipwright import ShipwrightBuildInfoResponse

        response = ShipwrightBuildInfoResponse(
            name="test-agent",
            namespace="team1",
            resourceType="agent",
            buildRegistered=True,
            outputImage="registry/test-agent:v1",
            strategy="buildah-insecure-push",
            gitUrl="https://github.com/example/repo",
            gitRevision="main",
            contextDir="agents/test",
        )

        assert response.name == "test-agent"
        assert response.hasBuildRun is False
        assert response.buildRunName is None
        assert response.buildRunPhase is None

    def test_response_with_buildrun(self):
        """Test response with BuildRun info."""
        from app.models.shipwright import ShipwrightBuildInfoResponse

        response = ShipwrightBuildInfoResponse(
            name="test-agent",
            namespace="team1",
            resourceType="agent",
            buildRegistered=True,
            outputImage="registry/test-agent:v1",
            strategy="buildah-insecure-push",
            gitUrl="https://github.com/example/repo",
            gitRevision="main",
            contextDir="agents/test",
            hasBuildRun=True,
            buildRunName="test-agent-run-abc123",
            buildRunPhase="Succeeded",
            buildRunStartTime="2025-01-20T10:00:00Z",
            buildRunCompletionTime="2025-01-20T10:05:00Z",
            buildRunOutputImage="registry/test-agent:v1",
            buildRunOutputDigest="sha256:abc123",
        )

        assert response.hasBuildRun is True
        assert response.buildRunName == "test-agent-run-abc123"
        assert response.buildRunPhase == "Succeeded"
        assert response.buildRunOutputDigest == "sha256:abc123"

    def test_response_with_failed_buildrun(self):
        """Test response with failed BuildRun."""
        from app.models.shipwright import ShipwrightBuildInfoResponse

        response = ShipwrightBuildInfoResponse(
            name="test-agent",
            namespace="team1",
            resourceType="agent",
            buildRegistered=True,
            outputImage="registry/test-agent:v1",
            strategy="buildah",
            gitUrl="https://github.com/example/repo",
            gitRevision="main",
            contextDir="agents/test",
            hasBuildRun=True,
            buildRunName="test-agent-run-xyz789",
            buildRunPhase="Failed",
            buildRunStartTime="2025-01-20T10:00:00Z",
            buildRunFailureMessage="Dockerfile not found in context",
        )

        assert response.hasBuildRun is True
        assert response.buildRunPhase == "Failed"
        assert response.buildRunFailureMessage == "Dockerfile not found in context"
        assert response.buildRunCompletionTime is None


class TestResolveCloneSecret:
    """Tests for resolve_clone_secret helper."""

    def test_returns_secret_name_when_exists(self):
        """Test that resolve_clone_secret returns the secret name when it exists."""
        from unittest.mock import MagicMock
        from app.services.shipwright import resolve_clone_secret

        mock_core_api = MagicMock()
        # read_namespaced_secret succeeds (secret exists)
        mock_core_api.read_namespaced_secret.return_value = MagicMock()

        result = resolve_clone_secret(mock_core_api, "team1")
        assert result == SHIPWRIGHT_GIT_SECRET_NAME
        mock_core_api.read_namespaced_secret.assert_called_once_with(
            name=SHIPWRIGHT_GIT_SECRET_NAME, namespace="team1"
        )

    def test_returns_none_when_missing(self):
        """Test that resolve_clone_secret returns None when the secret doesn't exist."""
        from unittest.mock import MagicMock
        from app.services.shipwright import resolve_clone_secret

        mock_core_api = MagicMock()
        mock_core_api.read_namespaced_secret.side_effect = Exception("Not found")

        result = resolve_clone_secret(mock_core_api, "team1")
        assert result is None
