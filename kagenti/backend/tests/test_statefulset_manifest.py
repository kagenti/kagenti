# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for StatefulSet manifest builder PVC wiring.

Mirrors the sandbox PVC tests so the two workload types stay in sync.
"""

from unittest.mock import MagicMock

from app.routers.agents import CreateAgentRequest, PersistentStorageConfig


def _make_request(**overrides):
    req = MagicMock(spec=CreateAgentRequest)
    req.name = overrides.get("name", "test-agent")
    req.namespace = overrides.get("namespace", "team1")
    req.containerImage = overrides.get("containerImage", "ghcr.io/example/agent:latest")
    req.framework = overrides.get("framework", "langgraph")
    req.protocol = overrides.get("protocol", "a2a")
    req.workloadType = overrides.get("workloadType", "statefulset")
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
    req.skills = overrides.get("skills", None)
    return req


class TestBuildStatefulsetManifestPVC:
    def test_no_pvc_by_default(self):
        from app.routers.agents import _build_statefulset_manifest

        request = _make_request()
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        assert "volumeClaimTemplates" not in manifest["spec"]
        volume_names = [v["name"] for v in manifest["spec"]["template"]["spec"]["volumes"]]
        assert "shared-data" in volume_names

    def test_pvc_when_enabled(self):
        from app.routers.agents import _build_statefulset_manifest

        storage = PersistentStorageConfig(enabled=True, size="5Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        vct = manifest["spec"]["volumeClaimTemplates"]
        assert len(vct) == 1
        assert vct[0]["metadata"]["name"] == "shared-data"
        assert vct[0]["metadata"]["labels"]["app.kubernetes.io/name"] == "test-agent"
        assert vct[0]["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert vct[0]["spec"]["resources"]["requests"]["storage"] == "5Gi"

    def test_pvc_replaces_shared_data_emptydir(self):
        from app.routers.agents import _build_statefulset_manifest

        storage = PersistentStorageConfig(enabled=True, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        volume_names = [v["name"] for v in manifest["spec"]["template"]["spec"]["volumes"]]
        assert "shared-data" not in volume_names
        assert "cache" in volume_names
        assert "marvin" in volume_names

    def test_pvc_volume_mount_unchanged(self):
        from app.routers.agents import _build_statefulset_manifest

        storage = PersistentStorageConfig(enabled=True, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        mount = next(m for m in container["volumeMounts"] if m["name"] == "shared-data")
        assert mount["mountPath"] == "/shared"

    def test_pvc_disabled_keeps_emptydir(self):
        from app.routers.agents import _build_statefulset_manifest

        storage = PersistentStorageConfig(enabled=False, size="1Gi")
        request = _make_request(persistentStorage=storage)
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        assert "volumeClaimTemplates" not in manifest["spec"]
        volume_names = [v["name"] for v in manifest["spec"]["template"]["spec"]["volumes"]]
        assert "shared-data" in volume_names

    def test_pvc_default_size(self):
        from app.routers.agents import _build_statefulset_manifest

        storage = PersistentStorageConfig(enabled=True)
        request = _make_request(persistentStorage=storage)
        manifest = _build_statefulset_manifest(request=request, image="test:latest")

        vct = manifest["spec"]["volumeClaimTemplates"]
        assert vct[0]["spec"]["resources"]["requests"]["storage"] == "1Gi"
