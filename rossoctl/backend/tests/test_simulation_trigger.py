# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the generation-trigger background task (issue #2162)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.routers import simulation as sim


@pytest.fixture(autouse=True)
def _skip_provision_wait():
    """These tests exercise the spec-POST loop; stub out the operator-adoption
    wait (_wait_for_runtime_configured) so it resolves immediately. The wait
    itself is covered by TestWaitForRuntimeConfigured below."""
    with patch(
        "app.routers.simulation._wait_for_runtime_configured",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.mark.asyncio
async def test_trigger_posts_once_on_202():
    post = AsyncMock(return_value=202)
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {"openapi": "3.0.0"}, 8000)
    post.assert_awaited_once()
    args = post.await_args.args
    assert args[0] == "http://petstore-mcp.team1.svc.cluster.local:8000"
    assert args[1] == {"openapi": "3.0.0"}
    assert args[2] == "petstore"


@pytest.mark.asyncio
async def test_trigger_treats_409_as_done():
    post = AsyncMock(return_value=409)
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    post.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_retries_until_harness_accepts():
    post = AsyncMock(side_effect=[sim.HarnessUnreachable("down"), 202])
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    assert post.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_gives_up_after_timeout():
    post = AsyncMock(side_effect=sim.HarnessUnreachable("down"))
    # monotonic: first read (start) = 0, subsequent reads jump past the deadline.
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()),
        patch("app.routers.simulation.time.monotonic", side_effect=[0, 1000, 1000]),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    # Deadline (0 + 600) is already passed on the first check (monotonic -> 1000),
    # so it posts exactly once, then gives up rather than looping.
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_trigger_retries_transient_5xx_then_succeeds():
    post = AsyncMock(side_effect=[503, 202])
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    assert post.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_terminal_4xx_does_not_retry():
    post = AsyncMock(return_value=422)
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.asyncio.sleep", new=AsyncMock()) as sleep,
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    post.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_swallows_unexpected_exception():
    # An unexpected error must not escape the fire-and-forget task.
    post = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch("app.routers.simulation.post_simulation", new=post),
        patch("app.routers.simulation.settings") as s,
    ):
        s.simulation_trigger_poll_interval = 5
        s.simulation_generation_timeout = 600
        # Should return normally, not raise.
        await sim._run_generation_trigger("team1", "petstore", {}, 8000)
    post.assert_awaited_once()
