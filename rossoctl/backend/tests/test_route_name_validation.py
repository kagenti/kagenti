# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Boundary-validation tests for agent route path params (rossoctl/rossoctl#2395,
extended for rossoctl/rossoctl#2457).

The `namespace` / `name` (and, on the dreaming routes, `agent`) path params on
the agent/tool-facing handlers are constrained to an RFC-1123 DNS label via
FastAPI ``Path(pattern=..., max_length=63)``, so injection characters (e.g. an
encoded newline) are rejected with 422 before any handler code — and can't
reach the loggers CodeQL flagged (py/log-injection).
"""

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import (
    agents,
    agents_migration,
    agents_shipwright,
    chat,
    dream,
    simulation,
    skills,
    tools,
)
from app.services.kubernetes import get_kubernetes_service


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(agents_migration.migration_router, prefix="/api/v1")
    app.include_router(agents_shipwright.shipwright_router, prefix="/api/v1")
    # agents.router pulls in migration_router/shipwright_router/finalize_router/
    # env_router/authbridge_router via its own include_router() calls, so this
    # single line also covers finalize_shipwright_build (#2457).
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(tools.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(simulation.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(dream.router, prefix="/api/v1")
    # Handlers never run for the invalid cases (422 at validation), but override the
    # kube dep so the valid-name case doesn't touch a real cluster.
    app.dependency_overrides[get_kubernetes_service] = lambda: MagicMock()
    with patch("app.core.auth.settings") as mock_auth:
        # Disable auth so the only thing that can fail is path-param validation.
        mock_auth.enable_auth = False
        # raise_server_exceptions=False: the positive-control tests below only
        # assert "not a 422" — a MagicMock kube can legitimately blow up deep
        # inside a handler's downstream k8s-object field access (that's not
        # what's under test here), and that must surface as a 500 response,
        # not an exception that aborts the test.
        yield TestClient(app, raise_server_exceptions=False)


# Names that violate the RFC-1123 DNS label (all must be rejected with 422).
_INVALID = {
    "newline": "bad%0Aname",  # the log-injection vector (encoded \n)
    "uppercase": "BadName",
    "dotted": "a.b",
    "underscore": "bad_name",
    "leading-hyphen": "-bad",
    "too-long": "a" * 64,
}


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_migrate_rejects_invalid_name(client, label, bad):
    r = client.post(f"/api/v1/default/{bad}/migrate")
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_migrate_rejects_invalid_namespace(client, label, bad):
    r = client.post(f"/api/v1/{bad}/my-agent/migrate")
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_shipwright_build_info_rejects_invalid_name(client, label, bad):
    r = client.get(f"/api/v1/default/{bad}/shipwright-build-info")
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


def test_valid_name_passes_validation(client):
    # A well-formed RFC-1123 name must NOT be rejected by the pattern (422). It may
    # succeed or fail downstream on the mocked kube call, but validation must pass.
    r = client.post("/api/v1/default/my-agent-1/migrate")
    assert r.status_code != 422, f"valid name wrongly rejected: {r.status_code}"


# ---------------------------------------------------------------------------
# #2457: additional routers whose namespace/name (or agent) path params were
# constrained to K8S_NAME_PATTERN. One representative GET route per router is
# enough to prove Path(pattern=...) is wired up; the pattern/max_length source
# is shared (app.utils.naming.K8S_NAME_PATTERN), so there's no need to re-test
# every handler in every file.
# ---------------------------------------------------------------------------

# (router label, URL template, valid-name URL) — `{bad}` is substituted with
# each entry from _INVALID for the negative tests.
_ROUTER_ROUTES = {
    "tools": (
        "/api/v1/tools/default/{bad}",
        "/api/v1/tools/default/my-tool-1",
    ),
    "agents": (
        "/api/v1/agents/default/{bad}",
        "/api/v1/agents/default/my-agent-1",
    ),
    "skills": (
        "/api/v1/skills/default/{bad}",
        "/api/v1/skills/default/my-skill-1",
    ),
    "simulation": (
        "/api/v1/simulation/tools/default/{bad}/generation-status",
        "/api/v1/simulation/tools/default/my-tool-1/generation-status",
    ),
    "chat": (
        "/api/v1/chat/default/{bad}/agent-card",
        "/api/v1/chat/default/my-agent-1/agent-card",
    ),
    "dream": (
        "/api/v1/dream/default/{bad}",
        "/api/v1/dream/default/my-agent-1",
    ),
}


@pytest.mark.parametrize("router_label", list(_ROUTER_ROUTES))
@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_router_rejects_invalid_name(client, router_label, label, bad):
    template, _valid = _ROUTER_ROUTES[router_label]
    r = client.get(template.format(bad=bad))
    assert r.status_code == 422, f"{router_label}/{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("router_label", list(_ROUTER_ROUTES))
@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_router_rejects_invalid_namespace(client, router_label, label, bad):
    template, _valid = _ROUTER_ROUTES[router_label]
    # Substitute the *namespace* slot instead of the name/agent slot: every
    # template above has exactly one "default/" segment for the namespace.
    url = template.format(bad="__NAME_PLACEHOLDER__").replace("default", bad, 1)
    url = url.replace("__NAME_PLACEHOLDER__", "my-agent-1")
    r = client.get(url)
    assert r.status_code == 422, f"{router_label}/{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("router_label", list(_ROUTER_ROUTES))
def test_router_valid_name_passes_validation(client, router_label):
    _template, valid = _ROUTER_ROUTES[router_label]
    r = client.get(valid)
    assert r.status_code != 422, f"{router_label}: valid name wrongly rejected: {r.status_code}"


# agents_finalize.finalize_shipwright_build is a POST (mounted under /agents via
# agents.router), so the GET-only _ROUTER_ROUTES table above can't reach it —
# exercise it directly to prove its Path(pattern=...) wiring. It requires a body
# (all fields optional), so send `json={}`: that keeps the body valid, so a 422
# can only come from the path-param name/namespace validation under test — not a
# missing body.
@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_finalize_shipwright_rejects_invalid_name(client, label, bad):
    r = client.post(f"/api/v1/agents/default/{bad}/finalize-shipwright-build", json={})
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_finalize_shipwright_rejects_invalid_namespace(client, label, bad):
    r = client.post(f"/api/v1/agents/{bad}/my-agent-1/finalize-shipwright-build", json={})
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


def test_finalize_shipwright_valid_name_passes_validation(client):
    r = client.post("/api/v1/agents/default/my-agent-1/finalize-shipwright-build", json={})
    assert r.status_code != 422, f"valid name wrongly rejected: {r.status_code}"


# ---------------------------------------------------------------------------
# agents_authbridge.py: the identity-config/identity-status routes are only
# registered at *import time* when rossoctl_feature_flag_authbridge_api is
# True (default False), so they aren't reachable through the `client` fixture
# above. Force the flag on and reload the module to register real routes on
# a fresh authbridge_router, mount that router in isolation, and verify the
# same Path(pattern=K8S_NAME_PATTERN) guard is in place — then reload again to
# restore the module to its default (flag-off) state.
# ---------------------------------------------------------------------------


@pytest.fixture
def authbridge_client():
    from app.routers import agents_authbridge

    try:
        with patch("app.core.config.settings.rossoctl_feature_flag_authbridge_api", True):
            importlib.reload(agents_authbridge)
            app = FastAPI()
            app.include_router(agents_authbridge.authbridge_router, prefix="/api/v1")
            app.dependency_overrides[get_kubernetes_service] = lambda: MagicMock()
            with patch("app.core.auth.settings") as mock_auth:
                mock_auth.enable_auth = False
                yield TestClient(app, raise_server_exceptions=False)
    finally:
        # Restore the module to its default (flag-off, no routes) state so it
        # doesn't leak a stray `authbridge_router` into other tests. This reload
        # runs OUTSIDE the flag patch above, so the module re-registers with the
        # real (off) flag value — reloading inside the patch would re-add the
        # routes and defeat the cleanup.
        importlib.reload(agents_authbridge)


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_authbridge_identity_config_rejects_invalid_name(authbridge_client, label, bad):
    r = authbridge_client.get(f"/api/v1/default/{bad}/identity-config")
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


@pytest.mark.parametrize("label,bad", _INVALID.items(), ids=list(_INVALID))
def test_authbridge_identity_config_rejects_invalid_namespace(authbridge_client, label, bad):
    r = authbridge_client.get(f"/api/v1/{bad}/my-agent-1/identity-config")
    assert r.status_code == 422, f"{label}: expected 422, got {r.status_code}"


def test_authbridge_identity_config_valid_name_passes_validation(authbridge_client):
    r = authbridge_client.get("/api/v1/default/my-agent-1/identity-config")
    assert r.status_code != 422, f"valid name wrongly rejected: {r.status_code}"


# ---------------------------------------------------------------------------
# acp.py: /ws/{namespace}/{agent_name} is a WebSocket route, so FastAPI's
# Path(pattern=...) 422 mechanism doesn't apply (there's no HTTP response on
# an upgrade). Instead the handler runs an equivalent runtime check against
# the same canonical K8S_NAME_RE before accepting the connection or logging
# anything derived from namespace/agent_name, and closes the socket with
# code 4400. Verify that behavior directly against the ASGI app (not through
# the `client` fixture's router set, since acp.router isn't included there).
# ---------------------------------------------------------------------------


def test_acp_websocket_closes_on_invalid_name():
    from fastapi import WebSocketDisconnect

    from app.routers import acp

    app = FastAPI()
    app.include_router(acp.router, prefix="/api/v1")
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.enable_auth = False
        with TestClient(app) as test_client:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_client.websocket_connect("/api/v1/acp/ws/default/bad%0Aname"):
                    pass
            assert exc_info.value.code == 4400
