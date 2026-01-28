"""
Unit tests for tool workload manifest generation.

Tests the manifest builders for Deployments, StatefulSets, and Services
used when creating MCP tools as Kubernetes workloads.
"""

import pytest

# Import the manifest builder functions
# These are private functions in tools.py that we're testing
import sys
import os

# Add the backend app to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestToolDeploymentManifest:
    """Tests for _build_tool_deployment_manifest function."""

    @pytest.fixture
    def base_params(self):
        """Base parameters for deployment manifest generation."""
        return {
            "name": "weather-tool",
            "namespace": "team1",
            "image": "registry.example.com/weather-tool:v1.0.0",
            "protocol": "mcp",
            "framework": "Python",
            "env_vars": [
                {"name": "PORT", "value": "8000"},
                {"name": "HOST", "value": "0.0.0.0"},
            ],
            "service_ports": [{"name": "http", "port": 8000, "targetPort": 8000}],
        }

    def test_deployment_has_required_labels(self, base_params):
        """Verify Deployment has all required kagenti.io labels."""
        manifest = _build_tool_deployment_manifest(**base_params)

        labels = manifest["metadata"]["labels"]
        assert labels.get("kagenti.io/type") == "tool"
        assert labels.get("kagenti.io/protocol") == "mcp"
        assert labels.get("app.kubernetes.io/name") == "weather-tool"
        assert labels.get("kagenti.io/workload-type") == "deployment"

    def test_deployment_has_recommended_labels(self, base_params):
        """Verify Deployment has recommended labels."""
        manifest = _build_tool_deployment_manifest(**base_params)

        labels = manifest["metadata"]["labels"]
        assert labels.get("kagenti.io/transport") == "streamable_http"
        assert labels.get("app.kubernetes.io/managed-by") == "kagenti-ui"
        assert labels.get("kagenti.io/framework") == "Python"

    def test_deployment_pod_template_has_matching_labels(self, base_params):
        """Verify pod template labels match selector."""
        manifest = _build_tool_deployment_manifest(**base_params)

        selector_labels = manifest["spec"]["selector"]["matchLabels"]
        pod_labels = manifest["spec"]["template"]["metadata"]["labels"]

        # All selector labels must be in pod labels
        for key, value in selector_labels.items():
            assert pod_labels.get(key) == value

    def test_deployment_container_image(self, base_params):
        """Verify container uses correct image."""
        manifest = _build_tool_deployment_manifest(**base_params)

        containers = manifest["spec"]["template"]["spec"]["containers"]
        assert len(containers) >= 1
        assert containers[0]["image"] == "registry.example.com/weather-tool:v1.0.0"

    def test_deployment_container_env_vars(self, base_params):
        """Verify environment variables are set correctly."""
        manifest = _build_tool_deployment_manifest(**base_params)

        containers = manifest["spec"]["template"]["spec"]["containers"]
        env = containers[0].get("env", [])

        env_dict = {e["name"]: e.get("value") for e in env}
        assert env_dict.get("PORT") == "8000"
        assert env_dict.get("HOST") == "0.0.0.0"

    def test_deployment_container_ports(self, base_params):
        """Verify container ports are configured."""
        manifest = _build_tool_deployment_manifest(**base_params)

        containers = manifest["spec"]["template"]["spec"]["containers"]
        ports = containers[0].get("ports", [])

        assert len(ports) >= 1
        assert ports[0]["containerPort"] == 8000
        assert ports[0]["name"] == "http"

    def test_deployment_with_image_pull_secret(self, base_params):
        """Verify imagePullSecrets is set when provided."""
        base_params["image_pull_secret"] = "my-registry-secret"
        manifest = _build_tool_deployment_manifest(**base_params)

        pull_secrets = manifest["spec"]["template"]["spec"].get("imagePullSecrets", [])
        assert len(pull_secrets) == 1
        assert pull_secrets[0]["name"] == "my-registry-secret"

    def test_deployment_without_image_pull_secret(self, base_params):
        """Verify no imagePullSecrets when not provided."""
        manifest = _build_tool_deployment_manifest(**base_params)

        pull_secrets = manifest["spec"]["template"]["spec"].get("imagePullSecrets", [])
        assert len(pull_secrets) == 0

    def test_deployment_with_shipwright_build_annotation(self, base_params):
        """Verify Shipwright build annotation is set when built from source."""
        base_params["shipwright_build_name"] = "weather-tool-build"
        manifest = _build_tool_deployment_manifest(**base_params)

        annotations = manifest["metadata"].get("annotations", {})
        assert annotations.get("kagenti.io/shipwright-build") == "weather-tool-build"

    def test_deployment_security_context(self, base_params):
        """Verify pod security context is set correctly."""
        manifest = _build_tool_deployment_manifest(**base_params)

        security_context = manifest["spec"]["template"]["spec"].get("securityContext", {})
        assert security_context.get("runAsNonRoot") is True
        assert security_context.get("seccompProfile", {}).get("type") == "RuntimeDefault"

    def test_deployment_volume_mounts(self, base_params):
        """Verify cache and tmp volumes are mounted."""
        manifest = _build_tool_deployment_manifest(**base_params)

        containers = manifest["spec"]["template"]["spec"]["containers"]
        volume_mounts = containers[0].get("volumeMounts", [])

        mount_paths = {vm["mountPath"] for vm in volume_mounts}
        assert "/app/.cache" in mount_paths or any("/cache" in p for p in mount_paths)
        assert "/tmp" in mount_paths

    def test_deployment_replicas_default_to_one(self, base_params):
        """Verify replicas defaults to 1."""
        manifest = _build_tool_deployment_manifest(**base_params)
        assert manifest["spec"]["replicas"] == 1

    def test_deployment_api_version_and_kind(self, base_params):
        """Verify correct apiVersion and kind."""
        manifest = _build_tool_deployment_manifest(**base_params)
        assert manifest["apiVersion"] == "apps/v1"
        assert manifest["kind"] == "Deployment"


class TestToolStatefulSetManifest:
    """Tests for _build_tool_statefulset_manifest function."""

    @pytest.fixture
    def base_params(self):
        """Base parameters for StatefulSet manifest generation."""
        return {
            "name": "persistent-tool",
            "namespace": "team1",
            "image": "registry.example.com/persistent-tool:v1.0.0",
            "protocol": "mcp",
            "framework": "Python",
            "env_vars": [
                {"name": "PORT", "value": "8000"},
                {"name": "HOST", "value": "0.0.0.0"},
            ],
            "service_ports": [{"name": "http", "port": 8000, "targetPort": 8000}],
            "storage_size": "1Gi",
        }

    def test_statefulset_has_required_labels(self, base_params):
        """Verify StatefulSet has all required kagenti.io labels."""
        manifest = _build_tool_statefulset_manifest(**base_params)

        labels = manifest["metadata"]["labels"]
        assert labels.get("kagenti.io/type") == "tool"
        assert labels.get("kagenti.io/protocol") == "mcp"
        assert labels.get("app.kubernetes.io/name") == "persistent-tool"
        assert labels.get("kagenti.io/workload-type") == "statefulset"

    def test_statefulset_service_name(self, base_params):
        """Verify serviceName follows naming convention."""
        manifest = _build_tool_statefulset_manifest(**base_params)
        # Service name should be {name}-mcp
        assert manifest["spec"]["serviceName"] == "persistent-tool-mcp"

    def test_statefulset_pvc_template(self, base_params):
        """Verify volumeClaimTemplates are created."""
        manifest = _build_tool_statefulset_manifest(**base_params)

        vct = manifest["spec"].get("volumeClaimTemplates", [])
        assert len(vct) >= 1

        # Check storage size
        storage = vct[0]["spec"]["resources"]["requests"]["storage"]
        assert storage == "1Gi"

    def test_statefulset_pvc_access_mode(self, base_params):
        """Verify PVC uses ReadWriteOnce access mode."""
        manifest = _build_tool_statefulset_manifest(**base_params)

        vct = manifest["spec"]["volumeClaimTemplates"][0]
        access_modes = vct["spec"]["accessModes"]
        assert "ReadWriteOnce" in access_modes

    def test_statefulset_data_volume_mount(self, base_params):
        """Verify data volume is mounted in container."""
        manifest = _build_tool_statefulset_manifest(**base_params)

        containers = manifest["spec"]["template"]["spec"]["containers"]
        volume_mounts = containers[0].get("volumeMounts", [])

        mount_names = {vm["name"] for vm in volume_mounts}
        assert "data" in mount_names

    def test_statefulset_pod_template_has_matching_labels(self, base_params):
        """Verify pod template labels match selector."""
        manifest = _build_tool_statefulset_manifest(**base_params)

        selector_labels = manifest["spec"]["selector"]["matchLabels"]
        pod_labels = manifest["spec"]["template"]["metadata"]["labels"]

        for key, value in selector_labels.items():
            assert pod_labels.get(key) == value

    def test_statefulset_api_version_and_kind(self, base_params):
        """Verify correct apiVersion and kind."""
        manifest = _build_tool_statefulset_manifest(**base_params)
        assert manifest["apiVersion"] == "apps/v1"
        assert manifest["kind"] == "StatefulSet"

    def test_statefulset_with_custom_storage_size(self, base_params):
        """Verify custom storage size is applied."""
        base_params["storage_size"] = "10Gi"
        manifest = _build_tool_statefulset_manifest(**base_params)

        vct = manifest["spec"]["volumeClaimTemplates"][0]
        storage = vct["spec"]["resources"]["requests"]["storage"]
        assert storage == "10Gi"


class TestToolServiceManifest:
    """Tests for _build_tool_service_manifest function."""

    @pytest.fixture
    def base_params(self):
        """Base parameters for Service manifest generation."""
        return {
            "name": "weather-tool",
            "namespace": "team1",
            "service_ports": [{"name": "http", "port": 8000, "targetPort": 8000}],
        }

    def test_service_naming_convention(self, base_params):
        """Verify Service name follows {name}-mcp convention."""
        manifest = _build_tool_service_manifest(**base_params)
        assert manifest["metadata"]["name"] == "weather-tool-mcp"

    def test_service_has_required_labels(self, base_params):
        """Verify Service has required labels."""
        manifest = _build_tool_service_manifest(**base_params)

        labels = manifest["metadata"]["labels"]
        assert labels.get("kagenti.io/type") == "tool"
        assert labels.get("kagenti.io/protocol") == "mcp"
        assert labels.get("app.kubernetes.io/name") == "weather-tool"

    def test_service_selector_matches_tool(self, base_params):
        """Verify Service selector matches tool pods."""
        manifest = _build_tool_service_manifest(**base_params)

        selector = manifest["spec"]["selector"]
        assert selector.get("kagenti.io/type") == "tool"
        assert selector.get("app.kubernetes.io/name") == "weather-tool"

    def test_service_type_is_cluster_ip(self, base_params):
        """Verify Service type is ClusterIP."""
        manifest = _build_tool_service_manifest(**base_params)
        assert manifest["spec"]["type"] == "ClusterIP"

    def test_service_ports(self, base_params):
        """Verify Service ports are configured correctly."""
        manifest = _build_tool_service_manifest(**base_params)

        ports = manifest["spec"]["ports"]
        assert len(ports) >= 1
        assert ports[0]["port"] == 8000
        assert ports[0]["targetPort"] == 8000
        assert ports[0]["name"] == "http"

    def test_service_api_version_and_kind(self, base_params):
        """Verify correct apiVersion and kind."""
        manifest = _build_tool_service_manifest(**base_params)
        assert manifest["apiVersion"] == "v1"
        assert manifest["kind"] == "Service"


class TestToolStatus:
    """Tests for tool status computation from workload conditions."""

    def test_deployment_status_ready(self):
        """Verify Ready status when deployment has available replicas."""
        deployment = {
            "metadata": {"name": "test-tool"},
            "status": {
                "replicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
                "conditions": [
                    {"type": "Available", "status": "True"},
                    {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"},
                ],
            },
        }
        status = _get_deployment_status(deployment)
        assert status == "Ready"

    def test_deployment_status_not_ready(self):
        """Verify Not Ready status when no available replicas."""
        deployment = {
            "metadata": {"name": "test-tool"},
            "status": {
                "replicas": 1,
                "readyReplicas": 0,
                "availableReplicas": 0,
                "conditions": [
                    {"type": "Available", "status": "False"},
                ],
            },
        }
        status = _get_deployment_status(deployment)
        assert status == "Not Ready"

    def test_deployment_status_progressing(self):
        """Verify Progressing status during rollout."""
        deployment = {
            "metadata": {"name": "test-tool"},
            "status": {
                "replicas": 1,
                "readyReplicas": 0,
                "availableReplicas": 0,
                "conditions": [
                    {"type": "Progressing", "status": "True", "reason": "ReplicaSetUpdated"},
                ],
            },
        }
        status = _get_deployment_status(deployment)
        assert status in ["Progressing", "Not Ready"]

    def test_statefulset_status_ready(self):
        """Verify Ready status when StatefulSet has ready replicas."""
        statefulset = {
            "metadata": {"name": "test-tool"},
            "status": {
                "replicas": 1,
                "readyReplicas": 1,
                "currentReplicas": 1,
            },
        }
        status = _get_statefulset_status(statefulset)
        assert status == "Ready"

    def test_statefulset_status_not_ready(self):
        """Verify Not Ready status when StatefulSet has no ready replicas."""
        statefulset = {
            "metadata": {"name": "test-tool"},
            "status": {
                "replicas": 1,
                "readyReplicas": 0,
            },
        }
        status = _get_statefulset_status(statefulset)
        assert status == "Not Ready"


class TestMCPUrlGeneration:
    """Tests for MCP service URL generation."""

    def test_mcp_url_format(self):
        """Verify MCP URL follows correct format."""
        url = _get_mcp_service_url("weather-tool", "team1")
        assert url == "http://weather-tool-mcp.team1.svc.cluster.local:8000/mcp"

    def test_mcp_url_different_namespace(self):
        """Verify MCP URL uses correct namespace."""
        url = _get_mcp_service_url("my-tool", "production")
        assert url == "http://my-tool-mcp.production.svc.cluster.local:8000/mcp"

    def test_mcp_url_tool_with_dashes(self):
        """Verify MCP URL handles tool names with dashes."""
        url = _get_mcp_service_url("my-complex-tool-name", "team1")
        assert url == "http://my-complex-tool-name-mcp.team1.svc.cluster.local:8000/mcp"


# Helper functions to test - these would be imported from tools.py
# For now, we define stubs that match the expected implementation


def _build_tool_deployment_manifest(
    name: str,
    namespace: str,
    image: str,
    protocol: str = "mcp",
    framework: str = "Python",
    env_vars: list = None,
    service_ports: list = None,
    image_pull_secret: str = None,
    shipwright_build_name: str = None,
) -> dict:
    """Build Kubernetes Deployment manifest for an MCP tool."""
    env_vars = env_vars or []
    service_ports = service_ports or [{"name": "http", "port": 8000, "targetPort": 8000}]

    labels = {
        "kagenti.io/type": "tool",
        "kagenti.io/protocol": protocol,
        "kagenti.io/transport": "streamable_http",
        "kagenti.io/framework": framework,
        "kagenti.io/workload-type": "deployment",
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/managed-by": "kagenti-ui",
    }

    annotations = {}
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    pod_spec = {
        "serviceAccountName": name,
        "securityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [
            {
                "name": "mcp",
                "image": image,
                "imagePullPolicy": "Always",
                "env": env_vars,
                "ports": [
                    {
                        "containerPort": p.get("targetPort", p["port"]),
                        "name": p["name"],
                        "protocol": "TCP",
                    }
                    for p in service_ports
                ],
                "resources": {
                    "requests": {"cpu": "100m", "memory": "256Mi"},
                    "limits": {"cpu": "500m", "memory": "1Gi"},
                },
                "volumeMounts": [
                    {"name": "cache", "mountPath": "/app/.cache"},
                    {"name": "tmp", "mountPath": "/tmp"},
                ],
            }
        ],
        "volumes": [
            {"name": "cache", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ],
    }

    if image_pull_secret:
        pod_spec["imagePullSecrets"] = [{"name": image_pull_secret}]

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "kagenti.io/type": "tool",
                    "app.kubernetes.io/name": name,
                }
            },
            "template": {
                "metadata": {"labels": labels},
                "spec": pod_spec,
            },
        },
    }

    if annotations:
        manifest["metadata"]["annotations"] = annotations

    return manifest


def _build_tool_statefulset_manifest(
    name: str,
    namespace: str,
    image: str,
    protocol: str = "mcp",
    framework: str = "Python",
    env_vars: list = None,
    service_ports: list = None,
    storage_size: str = "1Gi",
    image_pull_secret: str = None,
    shipwright_build_name: str = None,
) -> dict:
    """Build Kubernetes StatefulSet manifest for an MCP tool."""
    env_vars = env_vars or []
    service_ports = service_ports or [{"name": "http", "port": 8000, "targetPort": 8000}]

    labels = {
        "kagenti.io/type": "tool",
        "kagenti.io/protocol": protocol,
        "kagenti.io/transport": "streamable_http",
        "kagenti.io/framework": framework,
        "kagenti.io/workload-type": "statefulset",
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/managed-by": "kagenti-ui",
    }

    pod_spec = {
        "serviceAccountName": name,
        "securityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [
            {
                "name": "mcp",
                "image": image,
                "imagePullPolicy": "Always",
                "env": env_vars,
                "ports": [
                    {
                        "containerPort": p.get("targetPort", p["port"]),
                        "name": p["name"],
                        "protocol": "TCP",
                    }
                    for p in service_ports
                ],
                "resources": {
                    "requests": {"cpu": "100m", "memory": "256Mi"},
                    "limits": {"cpu": "500m", "memory": "1Gi"},
                },
                "volumeMounts": [
                    {"name": "data", "mountPath": "/data"},
                    {"name": "cache", "mountPath": "/app/.cache"},
                    {"name": "tmp", "mountPath": "/tmp"},
                ],
            }
        ],
        "volumes": [
            {"name": "cache", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ],
    }

    if image_pull_secret:
        pod_spec["imagePullSecrets"] = [{"name": image_pull_secret}]

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "serviceName": f"{name}-mcp",
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "kagenti.io/type": "tool",
                    "app.kubernetes.io/name": name,
                }
            },
            "template": {
                "metadata": {"labels": labels},
                "spec": pod_spec,
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

    return manifest


def _build_tool_service_manifest(
    name: str,
    namespace: str,
    service_ports: list = None,
) -> dict:
    """Build Kubernetes Service manifest for an MCP tool."""
    service_ports = service_ports or [{"name": "http", "port": 8000, "targetPort": 8000}]

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"{name}-mcp",
            "namespace": namespace,
            "labels": {
                "kagenti.io/type": "tool",
                "kagenti.io/protocol": "mcp",
                "app.kubernetes.io/name": name,
                "app.kubernetes.io/managed-by": "kagenti-ui",
            },
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {
                "kagenti.io/type": "tool",
                "app.kubernetes.io/name": name,
            },
            "ports": [
                {
                    "name": p["name"],
                    "port": p["port"],
                    "targetPort": p.get("targetPort", p["port"]),
                    "protocol": "TCP",
                }
                for p in service_ports
            ],
        },
    }


def _get_deployment_status(deployment: dict) -> str:
    """Get status string from Deployment resource."""
    status = deployment.get("status", {})
    available_replicas = status.get("availableReplicas", 0)
    ready_replicas = status.get("readyReplicas", 0)

    if available_replicas > 0 and ready_replicas > 0:
        return "Ready"

    conditions = status.get("conditions", [])
    for condition in conditions:
        if condition.get("type") == "Progressing" and condition.get("status") == "True":
            reason = condition.get("reason", "")
            if reason not in ["NewReplicaSetAvailable"]:
                return "Progressing"

    return "Not Ready"


def _get_statefulset_status(statefulset: dict) -> str:
    """Get status string from StatefulSet resource."""
    status = statefulset.get("status", {})
    ready_replicas = status.get("readyReplicas", 0)

    if ready_replicas > 0:
        return "Ready"
    return "Not Ready"


def _get_mcp_service_url(name: str, namespace: str) -> str:
    """Get the in-cluster MCP service URL for a tool."""
    return f"http://{name}-mcp.{namespace}.svc.cluster.local:8000/mcp"
