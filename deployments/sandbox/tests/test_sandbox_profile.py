"""Tests for SandboxProfile — composable name and manifest builder."""

import pytest

from sandbox_profile import SandboxProfile


class TestComposableName:
    """Agent name = base + active layer suffixes."""

    def test_name_no_layers(self):
        p = SandboxProfile(base_agent="sandbox-legion")
        assert p.name == "sandbox-legion"

    def test_name_secctx_only(self):
        p = SandboxProfile(base_agent="sandbox-legion", secctx=True)
        assert p.name == "sandbox-legion-secctx"

    def test_name_secctx_landlock(self):
        p = SandboxProfile(base_agent="sandbox-legion", secctx=True, landlock=True)
        assert p.name == "sandbox-legion-secctx-landlock"

    def test_name_full_stack(self):
        p = SandboxProfile(
            base_agent="sandbox-legion",
            secctx=True,
            landlock=True,
            proxy=True,
            gvisor=True,
        )
        assert p.name == "sandbox-legion-secctx-landlock-proxy-gvisor"

    def test_name_custom_combo_proxy_only(self):
        p = SandboxProfile(base_agent="sandbox-legion", proxy=True)
        assert p.name == "sandbox-legion-proxy"

    def test_name_custom_base_agent(self):
        p = SandboxProfile(base_agent="my-agent", secctx=True, landlock=True)
        assert p.name == "my-agent-secctx-landlock"


class TestWarnings:
    """Unusual combinations produce warnings."""

    def test_no_warnings_for_preset(self):
        p = SandboxProfile(
            base_agent="sandbox-legion", secctx=True, landlock=True, proxy=True
        )
        assert p.warnings == []

    def test_warning_proxy_without_secctx(self):
        p = SandboxProfile(base_agent="sandbox-legion", proxy=True)
        warnings = p.warnings
        assert len(warnings) == 1
        assert "SecurityContext" in warnings[0]

    def test_warning_landlock_without_secctx(self):
        p = SandboxProfile(base_agent="sandbox-legion", landlock=True)
        warnings = p.warnings
        assert len(warnings) == 1
        assert "SecurityContext" in warnings[0]

    def test_warning_gvisor_without_secctx(self):
        p = SandboxProfile(base_agent="sandbox-legion", gvisor=True)
        warnings = p.warnings
        assert any("SecurityContext" in w for w in warnings)


class TestManifestDeployment:
    """build_manifest() generates K8s Deployment by default."""

    def test_basic_deployment(self):
        p = SandboxProfile(base_agent="sandbox-legion")
        manifest = p.build_manifest()
        assert manifest["kind"] == "Deployment"
        assert manifest["metadata"]["name"] == "sandbox-legion"

    def test_secctx_in_manifest(self):
        p = SandboxProfile(base_agent="sandbox-legion", secctx=True)
        manifest = p.build_manifest()
        pod_sec = manifest["spec"]["template"]["spec"]["securityContext"]
        assert pod_sec["runAsNonRoot"] is True
        assert pod_sec["seccompProfile"]["type"] == "RuntimeDefault"

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        c_sec = container["securityContext"]
        assert c_sec["allowPrivilegeEscalation"] is False
        assert c_sec["readOnlyRootFilesystem"] is True
        assert c_sec["capabilities"]["drop"] == ["ALL"]

    def test_landlock_entrypoint(self):
        p = SandboxProfile(base_agent="sandbox-legion", landlock=True)
        manifest = p.build_manifest()
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        # Entrypoint should wrap with nono-launcher
        command = " ".join(container.get("command", []) + container.get("args", []))
        assert "nono_launcher" in command or "nono-launcher" in command

    def test_proxy_sidecar(self):
        p = SandboxProfile(base_agent="sandbox-legion", proxy=True)
        manifest = p.build_manifest()
        containers = manifest["spec"]["template"]["spec"]["containers"]
        names = [c["name"] for c in containers]
        assert "proxy" in names

        # Agent container should have HTTP_PROXY env
        agent = [c for c in containers if c["name"] == "agent"][0]
        env_names = [e["name"] for e in agent.get("env", [])]
        assert "HTTP_PROXY" in env_names
        assert "HTTPS_PROXY" in env_names

    def test_proxy_env_values(self):
        p = SandboxProfile(base_agent="sandbox-legion", proxy=True)
        manifest = p.build_manifest()
        agent = manifest["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in agent.get("env", [])}
        assert env["HTTP_PROXY"] == "http://localhost:3128"
        assert env["HTTPS_PROXY"] == "http://localhost:3128"

    def test_namespace_in_manifest(self):
        p = SandboxProfile(base_agent="sandbox-legion", namespace="team2")
        manifest = p.build_manifest()
        assert manifest["metadata"]["namespace"] == "team2"


class TestManifestSandboxClaim:
    """build_manifest() generates SandboxClaim when managed_lifecycle=True."""

    def test_sandboxclaim_kind(self):
        p = SandboxProfile(
            base_agent="sandbox-legion", managed_lifecycle=True, ttl_hours=4
        )
        manifest = p.build_manifest()
        assert manifest["kind"] == "SandboxClaim"
        assert manifest["apiVersion"] == "extensions.agents.x-k8s.io/v1alpha1"

    def test_sandboxclaim_lifecycle(self):
        p = SandboxProfile(
            base_agent="sandbox-legion", managed_lifecycle=True, ttl_hours=2
        )
        manifest = p.build_manifest()
        lifecycle = manifest["spec"]["lifecycle"]
        assert lifecycle["shutdownPolicy"] == "Delete"
        assert "shutdownTime" in lifecycle

    def test_sandboxclaim_template_ref(self):
        p = SandboxProfile(
            base_agent="sandbox-legion",
            secctx=True,
            landlock=True,
            managed_lifecycle=True,
        )
        manifest = p.build_manifest()
        assert "sandboxTemplateRef" in manifest["spec"]


class TestBuildService:
    """build_service() generates K8s Service."""

    def test_service_structure(self):
        p = SandboxProfile(base_agent="sandbox-legion", namespace="team1")
        svc = p.build_service()
        assert svc["kind"] == "Service"
        assert svc["metadata"]["name"] == "sandbox-legion"
        assert svc["spec"]["ports"][0]["port"] == 8080
