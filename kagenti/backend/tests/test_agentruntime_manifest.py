# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for _build_agentruntime_manifest and the CreateAgentRequest /
FinalizeShipwrightBuildRequest cross-field validator.

The operator's AgentRuntime CRD enum (disabled / permissive / strict)
is matched 1:1 by the backend's Pydantic Literal. The cross-field
"mtlsMode != disabled is incompatible with envoy-sidecar" rule is
mirrored here so the form gets a 422 before the manifest is built —
without this layer the user would only see the operator's webhook
denial, which lands later in the flow and is harder to surface
inline.
"""

import pytest
from pydantic import ValidationError


def test_manifest_omits_mtls_mode_when_unset():
    """No mtlsMode → no spec.mtlsMode key (lets operator default kick in)."""
    from app.routers.agents import _build_agentruntime_manifest

    m = _build_agentruntime_manifest("a", "ns", "deployment")
    assert "mtlsMode" not in m["spec"]


def test_manifest_includes_mtls_mode_when_set():
    """Each enum value flows into spec.mtlsMode unchanged."""
    from app.routers.agents import _build_agentruntime_manifest

    for mode in ("disabled", "permissive", "strict"):
        m = _build_agentruntime_manifest("a", "ns", "deployment", mtls_mode=mode)
        assert m["spec"]["mtlsMode"] == mode


def test_manifest_independent_of_auth_bridge_mode():
    """mtls_mode and auth_bridge_mode flow as independent fields.

    Cross-field validation lives in the request models, not the
    manifest builder — the builder is a dumb dict assembler.
    """
    from app.routers.agents import _build_agentruntime_manifest

    m = _build_agentruntime_manifest(
        "a", "ns", "deployment", auth_bridge_mode="proxy-sidecar", mtls_mode="strict"
    )
    assert m["spec"]["authBridgeMode"] == "proxy-sidecar"
    assert m["spec"]["mtlsMode"] == "strict"


def test_create_agent_request_accepts_disabled_with_envoy():
    """envoy-sidecar + disabled (the no-op combo) is allowed."""
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="envoy-sidecar",
        mtlsMode="disabled",
    )
    assert r.mtlsMode == "disabled"


def test_create_agent_request_rejects_envoy_with_strict():
    """The operator webhook will reject this; mirror the check here."""
    from app.routers.agents import CreateAgentRequest

    with pytest.raises(ValidationError) as exc_info:
        CreateAgentRequest(
            name="a",
            namespace="ns",
            authBridgeMode="envoy-sidecar",
            mtlsMode="strict",
        )
    msg = str(exc_info.value)
    # Forward-pointing error message is part of the contract — UI
    # surfaces this string to users.
    assert "envoy-sidecar" in msg
    assert "follow-up" in msg


def test_create_agent_request_rejects_envoy_with_permissive():
    from app.routers.agents import CreateAgentRequest

    with pytest.raises(ValidationError):
        CreateAgentRequest(
            name="a",
            namespace="ns",
            authBridgeMode="envoy-sidecar",
            mtlsMode="permissive",
        )


def test_create_agent_request_proxy_sidecar_allows_strict():
    """Most common case: proxy-sidecar + strict, the documented path."""
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="proxy-sidecar",
        mtlsMode="strict",
    )
    assert r.authBridgeMode == "proxy-sidecar"
    assert r.mtlsMode == "strict"


def test_create_agent_request_lite_allows_strict():
    """lite is a build variant of proxy-sidecar; same mtls compatibility."""
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="lite",
        mtlsMode="strict",
    )
    assert r.mtlsMode == "strict"


def test_finalize_shipwright_request_mirrors_validator():
    """Same cross-field rule on the build-finalize boundary."""
    from app.routers.agents import FinalizeShipwrightBuildRequest

    # Allowed
    FinalizeShipwrightBuildRequest(authBridgeMode="proxy-sidecar", mtlsMode="strict")
    # Rejected
    with pytest.raises(ValidationError):
        FinalizeShipwrightBuildRequest(authBridgeMode="envoy-sidecar", mtlsMode="strict")


def test_create_agent_request_default_mtls_mode_is_none():
    """Bare request → mtlsMode None → operator falls back to its default
    (disabled). Sending undefined on the wire keeps existing behavior
    byte-identical for users who haven't engaged the new feature.
    """
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(name="a", namespace="ns")
    assert r.mtlsMode is None


def test_create_agent_request_unknown_mtls_value_rejected():
    """Pydantic Literal enforcement — any non-enum value is rejected
    at the API layer, before the validator runs.
    """
    from app.routers.agents import CreateAgentRequest

    with pytest.raises(ValidationError):
        CreateAgentRequest(name="a", namespace="ns", mtlsMode="loose")
