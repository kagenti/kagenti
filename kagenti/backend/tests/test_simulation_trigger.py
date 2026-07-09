# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the generation-trigger background task (issue #2162)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.routers import simulation as sim


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
    # It attempted at least once and then gave up rather than looping forever.
    assert post.await_count >= 1
