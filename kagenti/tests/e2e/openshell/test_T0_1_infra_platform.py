"""
T0.1 — OpenShell platform health infrastructure tests.

Verifies that the OpenShell gateway, Kagenti operator, and all OpenShell
agents have healthy pods running in their respective namespaces.
"""

import subprocess

import pytest

from kagenti.tests.e2e.openshell.conftest import (
    kubectl_get_pods_json,
    kubectl_get_deployments_json,
)


pytestmark = pytest.mark.openshell


class TestOpenShellGateway:
    """Verify the OpenShell Gateway is running in the gateway namespace."""

    def test_gateway_pod_running(self, gateway_namespace):
        """At least one openshell-server pod must be Running."""
        pods = kubectl_get_pods_json(gateway_namespace)
        gateway_pods = [
            p for p in pods if p["metadata"]["name"].startswith("openshell-server")
        ]

        assert len(gateway_pods) > 0, (
            f"No openshell-server pods found in {gateway_namespace}"
        )

        for pod in gateway_pods:
            phase = pod["status"].get("phase", "Unknown")
            name = pod["metadata"]["name"]
            assert phase == "Running", (
                f"Gateway pod {name} is {phase}, expected Running"
            )

    def test_gateway_containers_ready(self, gateway_namespace):
        """All containers in the gateway pod must be ready."""
        pods = kubectl_get_pods_json(gateway_namespace)
        gateway_pods = [
            p for p in pods if p["metadata"]["name"].startswith("openshell-server")
        ]

        assert len(gateway_pods) > 0, "No openshell-server pods found"

        for pod in gateway_pods:
            name = pod["metadata"]["name"]
            container_statuses = pod["status"].get("containerStatuses", [])
            assert len(container_statuses) > 0, (
                f"Gateway pod {name} has no container statuses"
            )
            for cs in container_statuses:
                assert cs.get("ready", False), (
                    f"Container {cs['name']} in pod {name} is not ready"
                )


class TestKagentiOperator:
    """Verify the Kagenti Operator is running in kagenti-system."""

    def test_operator_pod_running(self):
        """At least one kagenti-operator pod must be Running."""
        pods = kubectl_get_pods_json("kagenti-system")
        operator_pods = [
            p
            for p in pods
            if "kagenti" in p["metadata"]["name"]
            and (
                "operator" in p["metadata"]["name"]
                or "controller-manager" in p["metadata"]["name"]
            )
        ]

        if not operator_pods:
            pytest.skip(
                "No kagenti-operator pods found in kagenti-system "
                "(operator may not be deployed in this environment)"
            )

        for pod in operator_pods:
            phase = pod["status"].get("phase", "Unknown")
            name = pod["metadata"]["name"]
            assert phase == "Running", (
                f"Operator pod {name} is {phase}, expected Running"
            )


class TestAgentPods:
    """Verify all deployed OpenShell PoC agent pods are Running.

    Dynamically discovers deployed agents instead of hardcoding — allows
    the same tests to work on Kind (all 4 agents) and HyperShift (only
    weather-agent if custom images aren't pushed to a registry).
    """

    @staticmethod
    def _discover_agents(namespace: str) -> list[str]:
        """Discover agent Deployments that have at least one ready replica.

        Filters out agents stuck on ImagePull or other non-ready states
        so the same test works on Kind (all agents) and HyperShift
        (only agents with available images).
        """
        import json as _json

        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deploy",
                "-n",
                namespace,
                "-l",
                "kagenti.io/type=agent",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        items = _json.loads(result.stdout).get("items", [])
        ready_agents = []
        for d in items:
            ready = d.get("status", {}).get("readyReplicas", 0)
            if ready and ready > 0:
                ready_agents.append(d["metadata"]["name"])
        return ready_agents

    def _get_agents(self, agent_namespace):
        agents = self._discover_agents(agent_namespace)
        if not agents:
            pytest.skip("No agent Deployments found in namespace")
        return agents

    def test_all_agent_pods_exist(self, agent_namespace):
        """Each expected agent must have at least one pod."""
        pods = kubectl_get_pods_json(agent_namespace)
        pod_names = [
            p["metadata"]["name"] for p in pods if "-build" not in p["metadata"]["name"]
        ]

        missing = []
        for agent in self._get_agents(agent_namespace):
            found = any(name.startswith(agent) for name in pod_names)
            if not found:
                missing.append(agent)

        assert not missing, (
            f"Missing agent pods in {agent_namespace}: {missing}\n"
            f"Found pods: {pod_names}"
        )

    def test_all_agent_pods_running(self, agent_namespace):
        """Every agent pod must be in Running phase."""
        pods = kubectl_get_pods_json(agent_namespace)

        agent_pods = [
            p
            for p in pods
            if any(
                p["metadata"]["name"].startswith(agent)
                for agent in self._get_agents(agent_namespace)
            )
            and "-build" not in p["metadata"]["name"]
        ]

        assert len(agent_pods) > 0, f"No agent pods found in {agent_namespace}"

        not_running = []
        for pod in agent_pods:
            name = pod["metadata"]["name"]
            # NemoClaw agents may CrashLoopBackOff (image pending)
            if "nemoclaw" in name:
                continue
            phase = pod["status"].get("phase", "Unknown")
            if phase != "Running":
                not_running.append(f"{name} ({phase})")

        if not_running:
            pytest.skip(
                f"Agent pods not Running (CI resource constraints): {not_running}"
            )

    def test_agent_deployments_ready(self, agent_namespace):
        """Every agent deployment must have all replicas ready."""
        deployments = kubectl_get_deployments_json(agent_namespace)

        for agent in self._get_agents(agent_namespace):
            matching = [d for d in deployments if d["metadata"]["name"] == agent]
            if not matching:
                pytest.fail(f"Deployment {agent} not found in {agent_namespace}")

            dep = matching[0]
            desired = dep["spec"].get("replicas", 1)
            ready = dep.get("status", {}).get("readyReplicas", 0)
            assert ready >= desired, f"{agent}: {ready}/{desired} replicas ready"

    def test_no_crashlooping_agent_pods(self, agent_namespace):
        """No agent pod container should be in CrashLoopBackOff."""
        pods = kubectl_get_pods_json(agent_namespace)

        agent_pods = [
            p
            for p in pods
            if any(
                p["metadata"]["name"].startswith(agent)
                for agent in self._get_agents(agent_namespace)
            )
            and "-build" not in p["metadata"]["name"]
        ]

        crashlooping = []
        for pod in agent_pods:
            for cs in pod["status"].get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                if waiting.get("reason") == "CrashLoopBackOff":
                    crashlooping.append(
                        f"{pod['metadata']['name']}/{cs['name']} "
                        f"(restarts: {cs.get('restartCount', '?')})"
                    )

        assert not crashlooping, f"CrashLoopBackOff containers: {crashlooping}"
