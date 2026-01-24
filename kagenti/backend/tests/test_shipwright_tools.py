# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for Tool Shipwright build functionality.

Tests cover:
- Tool Build manifest generation for various scenarios
- Tool BuildRun manifest generation
- Tool config annotation storage/retrieval
- Finalize tool build logic
- Delete tool with Shipwright cleanup
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.routers.tools import (
    CreateToolRequest,
    FinalizeToolBuildRequest,
    ToolShipwrightBuildInfoResponse,
    _build_tool_shipwright_build_manifest,
    _build_tool_shipwright_buildrun_manifest,
    _build_mcpserver_manifest,
)
from app.models.shipwright import (
    ResourceType,
    ShipwrightBuildConfig,
    BuildSourceConfig,
    BuildOutputConfig,
    ResourceConfigFromBuild,
)
from app.services.shipwright import (
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    extract_resource_config_from_build,
    select_build_strategy,
)
from app.core.constants import (
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_STRATEGY_INSECURE,
    SHIPWRIGHT_STRATEGY_SECURE,
    DEFAULT_INTERNAL_REGISTRY,
    KAGENTI_TYPE_LABEL,
    KAGENTI_PROTOCOL_LABEL,
    KAGENTI_FRAMEWORK_LABEL,
    RESOURCE_TYPE_TOOL,
)


class TestToolBuildManifestGeneration:
    """Tests for tool Build manifest generation."""

    def test_basic_tool_build_manifest_internal_registry(self):
        """Test basic tool build manifest generation for internal registry."""
        request = CreateToolRequest(
            name="weather-tool",
            namespace="team1",
            protocol="streamable_http",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/kagenti/agent-examples",
            gitRevision="main",
            contextDir="mcp/weather_tool",
            imageTag="v0.0.1",
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Check API version and kind
        assert manifest["apiVersion"] == f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}"
        assert manifest["kind"] == "Build"

        # Check metadata
        assert manifest["metadata"]["name"] == "weather-tool"
        assert manifest["metadata"]["namespace"] == "team1"
        assert manifest["metadata"]["labels"][KAGENTI_TYPE_LABEL] == RESOURCE_TYPE_TOOL
        assert manifest["metadata"]["labels"][KAGENTI_PROTOCOL_LABEL] == "streamable_http"
        assert manifest["metadata"]["labels"][KAGENTI_FRAMEWORK_LABEL] == "Python"

        # Check source configuration
        assert manifest["spec"]["source"]["type"] == "Git"
        assert (
            manifest["spec"]["source"]["git"]["url"] == "https://github.com/kagenti/agent-examples"
        )
        assert manifest["spec"]["source"]["git"]["revision"] == "main"
        assert manifest["spec"]["source"]["contextDir"] == "mcp/weather_tool"

        # Check strategy - should be insecure for internal registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_INSECURE
        assert manifest["spec"]["strategy"]["kind"] == "ClusterBuildStrategy"

        # Check output image
        expected_image = f"{DEFAULT_INTERNAL_REGISTRY}/weather-tool:v0.0.1"
        assert manifest["spec"]["output"]["image"] == expected_image

    def test_tool_build_manifest_external_registry(self):
        """Test tool build manifest generation for external registry (quay.io)."""
        request = CreateToolRequest(
            name="weather-tool",
            namespace="team1",
            protocol="streamable_http",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/kagenti/agent-examples",
            gitRevision="main",
            contextDir="mcp/weather_tool",
            registryUrl="quay.io/myorg",
            registrySecret="quay-registry-secret",
            imageTag="v1.0.0",
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Check strategy - should be secure for external registry
        assert manifest["spec"]["strategy"]["name"] == SHIPWRIGHT_STRATEGY_SECURE

        # Check output image
        assert manifest["spec"]["output"]["image"] == "quay.io/myorg/weather-tool:v1.0.0"

        # Check push secret
        assert manifest["spec"]["output"]["pushSecret"] == "quay-registry-secret"

    def test_tool_build_manifest_with_custom_config(self):
        """Test tool build manifest with custom Shipwright config."""
        # Use external registry to test custom strategy (internal registry overrides
        # secure strategy to insecure for TLS-less pushes)
        request = CreateToolRequest(
            name="custom-tool",
            namespace="team1",
            protocol="sse",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/example/tools",
            gitRevision="develop",
            contextDir="tools/custom",
            registryUrl="quay.io/myorg",
            registrySecret="quay-secret",
            imageTag="v2.0.0",
            shipwrightConfig=ShipwrightBuildConfig(
                buildStrategy="buildah",
                dockerfile="Dockerfile.prod",
                buildTimeout="30m",
                buildArgs=["BUILD_ENV=production", "VERSION=2.0.0"],
            ),
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Check custom strategy is respected for external registry
        assert manifest["spec"]["strategy"]["name"] == "buildah"

        # Check timeout
        assert manifest["spec"]["timeout"] == "30m"

        # Check param values for dockerfile and build args
        param_values = {
            p["name"]: p.get("value") or p.get("values") for p in manifest["spec"]["paramValues"]
        }
        assert param_values.get("dockerfile") == "Dockerfile.prod"
        # build-args are stored as list of dicts with 'value' key
        build_args = param_values.get("build-args", [])
        build_arg_values = [
            arg.get("value") if isinstance(arg, dict) else arg for arg in build_args
        ]
        assert "BUILD_ENV=production" in build_arg_values
        assert "VERSION=2.0.0" in build_arg_values

    def test_tool_build_manifest_stores_tool_config(self):
        """Test that tool config is stored in Build annotations."""
        request = CreateToolRequest(
            name="annotated-tool",
            namespace="team1",
            protocol="streamable_http",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/example/tools",
            contextDir="tools/annotated",
            createHttpRoute=True,
            registrySecret="my-secret",
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Check annotation exists
        assert "kagenti.io/tool-config" in manifest["metadata"]["annotations"]

        # Parse and verify tool config
        tool_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/tool-config"])
        assert tool_config["protocol"] == "streamable_http"
        assert tool_config["framework"] == "Python"
        assert tool_config["createHttpRoute"] is True
        assert tool_config["registrySecret"] == "my-secret"

    def test_tool_build_manifest_with_env_vars(self):
        """Test tool build manifest stores env vars in config annotation."""
        from app.routers.tools import EnvVar

        request = CreateToolRequest(
            name="env-tool",
            namespace="team1",
            protocol="streamable_http",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/example/tools",
            contextDir="tools/env",
            envVars=[
                EnvVar(name="API_KEY", value="secret123"),
                EnvVar(name="DEBUG", value="true"),
            ],
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Parse tool config from annotation
        tool_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/tool-config"])
        assert "envVars" in tool_config
        assert len(tool_config["envVars"]) == 2
        assert tool_config["envVars"][0]["name"] == "API_KEY"
        assert tool_config["envVars"][1]["name"] == "DEBUG"

    def test_tool_build_manifest_with_service_ports(self):
        """Test tool build manifest stores service ports in config annotation."""
        from app.routers.tools import ServicePort

        request = CreateToolRequest(
            name="ports-tool",
            namespace="team1",
            protocol="streamable_http",
            framework="Python",
            deploymentMethod="source",
            gitUrl="https://github.com/example/tools",
            contextDir="tools/ports",
            servicePorts=[
                ServicePort(name="http", port=8080, targetPort=8000, protocol="TCP"),
                ServicePort(name="grpc", port=9090, targetPort=9000, protocol="TCP"),
            ],
        )

        manifest = _build_tool_shipwright_build_manifest(request)

        # Parse tool config from annotation
        tool_config = json.loads(manifest["metadata"]["annotations"]["kagenti.io/tool-config"])
        assert "servicePorts" in tool_config
        assert len(tool_config["servicePorts"]) == 2
        assert tool_config["servicePorts"][0]["name"] == "http"
        assert tool_config["servicePorts"][0]["port"] == 8080


class TestToolBuildRunManifestGeneration:
    """Tests for tool BuildRun manifest generation."""

    def test_basic_tool_buildrun_manifest(self):
        """Test basic tool BuildRun manifest generation."""
        manifest = _build_tool_shipwright_buildrun_manifest(
            build_name="weather-tool",
            namespace="team1",
        )

        # Check API version and kind
        assert manifest["apiVersion"] == f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}"
        assert manifest["kind"] == "BuildRun"

        # Check metadata
        assert manifest["metadata"]["generateName"] == "weather-tool-run-"
        assert manifest["metadata"]["namespace"] == "team1"

        # Check build reference
        assert manifest["spec"]["build"]["name"] == "weather-tool"

    def test_tool_buildrun_manifest_with_labels(self):
        """Test tool BuildRun manifest includes labels."""
        labels = {
            "kagenti.io/protocol": "streamable_http",
            "kagenti.io/framework": "Python",
        }

        manifest = _build_tool_shipwright_buildrun_manifest(
            build_name="labeled-tool",
            namespace="team1",
            labels=labels,
        )

        # Check labels are propagated
        assert manifest["metadata"]["labels"]["kagenti.io/protocol"] == "streamable_http"
        assert manifest["metadata"]["labels"]["kagenti.io/framework"] == "Python"
        assert manifest["metadata"]["labels"]["kagenti.io/build-name"] == "labeled-tool"

    def test_tool_buildrun_uses_generate_name(self):
        """Test that BuildRun uses generateName for unique naming."""
        manifest = _build_tool_shipwright_buildrun_manifest(
            build_name="my-tool",
            namespace="team1",
        )

        assert "generateName" in manifest["metadata"]
        assert "name" not in manifest["metadata"]
        assert manifest["metadata"]["generateName"].startswith("my-tool-run-")


class TestToolConfigExtraction:
    """Tests for extracting tool config from Build annotations."""

    def test_extract_tool_config_from_build(self):
        """Test extracting tool config from Build annotations."""
        build = {
            "metadata": {
                "name": "test-tool",
                "namespace": "team1",
                "annotations": {
                    "kagenti.io/tool-config": json.dumps(
                        {
                            "protocol": "streamable_http",
                            "framework": "Python",
                            "createHttpRoute": True,
                            "registrySecret": "my-secret",
                        }
                    )
                },
            }
        }

        config = extract_resource_config_from_build(build, ResourceType.TOOL)

        assert config is not None
        assert config.protocol == "streamable_http"
        assert config.framework == "Python"
        assert config.createHttpRoute is True
        assert config.registrySecret == "my-secret"

    def test_extract_tool_config_missing_annotation(self):
        """Test extracting tool config when annotation is missing."""
        build = {"metadata": {"name": "test-tool", "namespace": "team1", "annotations": {}}}

        config = extract_resource_config_from_build(build, ResourceType.TOOL)
        assert config is None

    def test_extract_tool_config_no_annotations(self):
        """Test extracting tool config when annotations dict is missing."""
        build = {
            "metadata": {
                "name": "test-tool",
                "namespace": "team1",
            }
        }

        config = extract_resource_config_from_build(build, ResourceType.TOOL)
        assert config is None

    def test_extract_tool_config_malformed_json(self):
        """Test extracting tool config with malformed JSON."""
        build = {
            "metadata": {
                "name": "test-tool",
                "namespace": "team1",
                "annotations": {"kagenti.io/tool-config": "not-valid-json"},
            }
        }

        config = extract_resource_config_from_build(build, ResourceType.TOOL)
        assert config is None

    def test_extract_tool_config_with_env_vars(self):
        """Test extracting tool config that includes env vars."""
        build = {
            "metadata": {
                "name": "test-tool",
                "namespace": "team1",
                "annotations": {
                    "kagenti.io/tool-config": json.dumps(
                        {
                            "protocol": "streamable_http",
                            "framework": "Python",
                            "createHttpRoute": False,
                            "envVars": [
                                {"name": "API_KEY", "value": "secret"},
                                {"name": "DEBUG", "value": "true"},
                            ],
                        }
                    )
                },
            }
        }

        config = extract_resource_config_from_build(build, ResourceType.TOOL)

        assert config is not None
        assert config.envVars is not None
        assert len(config.envVars) == 2
        assert config.envVars[0]["name"] == "API_KEY"


class TestToolBuildInfoResponse:
    """Tests for ToolShipwrightBuildInfoResponse model."""

    def test_build_info_response_basic(self):
        """Test basic build info response structure."""
        response = ToolShipwrightBuildInfoResponse(
            name="weather-tool",
            namespace="team1",
            buildRegistered=True,
            outputImage="registry.local/weather-tool:v0.0.1",
            strategy="buildah-insecure-push",
            gitUrl="https://github.com/example/tools",
            gitRevision="main",
            contextDir="mcp/weather_tool",
        )

        assert response.name == "weather-tool"
        assert response.namespace == "team1"
        assert response.buildRegistered is True
        assert response.hasBuildRun is False
        assert response.buildRunName is None
        assert response.toolConfig is None

    def test_build_info_response_with_buildrun(self):
        """Test build info response with BuildRun info."""
        response = ToolShipwrightBuildInfoResponse(
            name="weather-tool",
            namespace="team1",
            buildRegistered=True,
            outputImage="registry.local/weather-tool:v0.0.1",
            strategy="buildah-insecure-push",
            gitUrl="https://github.com/example/tools",
            gitRevision="main",
            contextDir="mcp/weather_tool",
            hasBuildRun=True,
            buildRunName="weather-tool-run-abc123",
            buildRunPhase="Succeeded",
            buildRunStartTime="2026-01-21T10:00:00Z",
            buildRunCompletionTime="2026-01-21T10:05:00Z",
            buildRunOutputImage="registry.local/weather-tool:v0.0.1",
            buildRunOutputDigest="sha256:abc123",
        )

        assert response.hasBuildRun is True
        assert response.buildRunName == "weather-tool-run-abc123"
        assert response.buildRunPhase == "Succeeded"
        assert response.buildRunOutputDigest == "sha256:abc123"

    def test_build_info_response_with_tool_config(self):
        """Test build info response with tool config."""
        tool_config = ResourceConfigFromBuild(
            protocol="streamable_http",
            framework="Python",
            createHttpRoute=True,
        )

        response = ToolShipwrightBuildInfoResponse(
            name="weather-tool",
            namespace="team1",
            buildRegistered=True,
            outputImage="registry.local/weather-tool:v0.0.1",
            strategy="buildah-insecure-push",
            gitUrl="https://github.com/example/tools",
            gitRevision="main",
            contextDir="mcp/weather_tool",
            toolConfig=tool_config,
        )

        assert response.toolConfig is not None
        assert response.toolConfig.protocol == "streamable_http"
        assert response.toolConfig.createHttpRoute is True


class TestMCPServerManifestGeneration:
    """Tests for MCPServer manifest generation."""

    def test_mcpserver_manifest_from_image(self):
        """Test MCPServer manifest for image deployment."""
        request = CreateToolRequest(
            name="image-tool",
            namespace="team1",
            deploymentMethod="image",
            containerImage="quay.io/myorg/my-tool:v1.0.0",
            protocol="streamable_http",
            framework="Python",
        )

        manifest = _build_mcpserver_manifest(request)

        assert manifest["kind"] == "MCPServer"
        assert manifest["metadata"]["name"] == "image-tool"
        assert manifest["metadata"]["namespace"] == "team1"
        assert manifest["spec"]["image"] == "quay.io/myorg/my-tool:v1.0.0"

    def test_mcpserver_manifest_with_image_pull_secret(self):
        """Test MCPServer manifest includes image pull secret."""
        request = CreateToolRequest(
            name="private-tool",
            namespace="team1",
            deploymentMethod="image",
            containerImage="private.registry/my-tool:v1.0.0",
            imagePullSecret="my-pull-secret",
            protocol="streamable_http",
            framework="Python",
        )

        manifest = _build_mcpserver_manifest(request)

        # Check imagePullSecrets in pod spec
        pod_spec = manifest["spec"]["podTemplateSpec"]["spec"]
        assert "imagePullSecrets" in pod_spec
        assert pod_spec["imagePullSecrets"][0]["name"] == "my-pull-secret"
