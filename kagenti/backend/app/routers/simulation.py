# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Simulated MCP tools API endpoints.

Scaffold for the simulated-tools feature (epic #2151). This router is only
mounted when ``kagenti_feature_flag_simulated_tools`` is enabled (see
``app/main.py``). Real endpoints — workload provisioning, generation
orchestration, lifecycle, and database re-seed — attach in later issues. For
now a single health/no-op endpoint proves the flag-gated wiring.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulation", tags=["simulation"])


class SimulationHealthResponse(BaseModel):
    """Health response confirming the simulation router is mounted."""

    status: str


@router.get("/health", response_model=SimulationHealthResponse)
async def simulation_health() -> SimulationHealthResponse:
    """Return OK when the flag-gated simulation router is mounted."""
    logger.debug("simulation router health check")
    return SimulationHealthResponse(status="ok")
