# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the provisioning gate that defers the spec POST until the operator
has adopted the simulated-tool workload via its AgentRuntime.

Kept in a separate module from test_simulation_trigger.py so it is not affected
by that module's autouse fixture, which stubs _wait_for_runtime_configured to
exercise the POST loop in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes.client import ApiException

from app.routers import simulation as sim


def _runtime_cr(*, ready: bool, configured_pods: int) -> dict:
    return {
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "configuredPods": configured_pods,
        }
    }


@pytest.mark.asyncio
async def test_returns_true_when_ready_and_pod_configured():
    kube = MagicMock()
    kube.get_custom_resource.return_value = _runtime_cr(ready=True, configured_pods=1)
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 180
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is True
    kube.get_custom_resource.assert_called()


@pytest.mark.asyncio
async def test_polls_until_configured():
    kube = MagicMock()
    kube.get_custom_resource.side_effect = [
        _runtime_cr(ready=False, configured_pods=0),  # not ready yet
        _runtime_cr(ready=True, configured_pods=0),  # ready, pod still rolling
        _runtime_cr(ready=True, configured_pods=1),  # configured
    ]
    sleep = AsyncMock()
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.asyncio.sleep", new=sleep),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 180
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is True
    assert kube.get_custom_resource.call_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_returns_false_on_timeout():
    kube = MagicMock()
    kube.get_custom_resource.return_value = _runtime_cr(ready=False, configured_pods=0)
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 0  # deadline already passed -> one look, then bail
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is False


@pytest.mark.asyncio
async def test_transient_read_error_is_retried_not_fatal():
    kube = MagicMock()
    kube.get_custom_resource.side_effect = [
        RuntimeError("api blip"),
        _runtime_cr(ready=True, configured_pods=1),
    ]
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 180
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is True
    assert kube.get_custom_resource.call_count == 2


@pytest.mark.asyncio
async def test_agentruntime_404_short_circuits_immediately():
    # Tool deleted mid-provisioning: a 404 on the CR means there's nothing left to
    # wait for, so give up at once rather than retrying (and log-spamming) until
    # the provision timeout.
    kube = MagicMock()
    kube.get_custom_resource.side_effect = ApiException(status=404)
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 180
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is False
    kube.get_custom_resource.assert_called_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_404_api_error_is_retried():
    kube = MagicMock()
    kube.get_custom_resource.side_effect = [
        ApiException(status=500),  # transient server error — retry
        _runtime_cr(ready=True, configured_pods=1),
    ]
    with (
        patch("app.routers.simulation.get_kubernetes_service", return_value=kube),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_provision_timeout = 180
        s.simulation_trigger_poll_interval = 5
        assert await sim._wait_for_runtime_configured("team1", "petstore") is True
    assert kube.get_custom_resource.call_count == 2
