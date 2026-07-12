# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Async HTTP client for the simulation harness control plane (issue #2162).

Thin wrappers over the harness REST API at `/api/v1/simulation`. Each call
creates its own short-lived `httpx.AsyncClient`, matching the in-cluster HTTP
call pattern used elsewhere in the backend (e.g. skill_autosync, sidecar_manager).
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class HarnessUnreachable(Exception):  # noqa: N818
    """The harness could not be contacted (any transport-level error: connect,
    read, write, timeout, or protocol — typically while the pod is starting)."""


class HarnessNotFound(Exception):  # noqa: N818
    """The harness is up but reports no active simulation (HTTP 404)."""


def _timeout() -> float:
    return settings.simulation_harness_request_timeout


async def get_simulation(base_url: str) -> dict:
    """GET the harness's active-simulation record.

    Returns the parsed SimulationResponse dict. Raises HarnessNotFound on 404
    (no simulation active yet) and HarnessUnreachable on connect/timeout.
    """
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.get(f"{base_url}/api/v1/simulation")
        except httpx.TransportError as e:
            # Base class for connect/read/write/timeout/protocol errors. A
            # starting harness often accepts the TCP connection then resets it
            # mid-read (ReadError) before uvicorn is serving — treat every
            # transport-level failure as "unreachable" so callers retry through
            # the pod's startup window instead of giving up on the first hiccup.
            raise HarnessUnreachable(str(e)) from e
        if resp.status_code == 404:
            raise HarnessNotFound("harness reports no active simulation")
        resp.raise_for_status()
        return resp.json()


async def post_simulation(base_url: str, spec: dict, name: str) -> int:
    """POST the OpenAPI spec to start generation. Returns the HTTP status code.

    202 = accepted (generating in background); 409 = already active. Raises
    HarnessUnreachable on connect/timeout.
    """
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.post(
                f"{base_url}/api/v1/simulation",
                json={"openapi_spec": spec, "name": name},
            )
        except httpx.TransportError as e:
            # Base class for connect/read/write/timeout/protocol errors. A
            # starting harness often accepts the TCP connection then resets it
            # mid-read (ReadError) before uvicorn is serving — treat every
            # transport-level failure as "unreachable" so callers retry through
            # the pod's startup window instead of giving up on the first hiccup.
            raise HarnessUnreachable(str(e)) from e
        return resp.status_code


async def reset_simulation(base_url: str) -> int:
    """POST the harness reset endpoint. Returns the HTTP status code.

    200 = session reset; 404 = no active simulation; 503 = exists but not ready.
    Raises HarnessUnreachable on connect/timeout.
    """
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.post(f"{base_url}/api/v1/simulation/reset")
        except httpx.TransportError as e:
            raise HarnessUnreachable(str(e)) from e
        return resp.status_code


async def put_database(base_url: str, db: dict) -> tuple[int, dict]:
    """PUT a new db.json to the harness. Returns (status_code, parsed_body).

    200 = replaced + session reset; 404 = no simulation; 409 = tool calls in
    flight; 422 = body failed schema validation (body carries json_path);
    503 = simulation exists but not ready. Raises HarnessUnreachable on
    connect/timeout. Body is {} when the response has no JSON object.
    """
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.put(f"{base_url}/api/v1/simulation/database", json=db)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HarnessUnreachable(str(e)) from e
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return resp.status_code, body
