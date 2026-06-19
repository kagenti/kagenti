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


def test_create_agent_request_allows_envoy_with_strict():
    """envoy-sidecar + strict is now supported end-to-end. Locked in
    here so a future regression that re-introduces the rejection gets
    caught by tests instead of breaking the user-facing form.

    Pairs with kagenti-operator#381 (operator wires Spec.MTLSMode
    into a per-agent envoy-config CM with TLS blocks) and
    kagenti-extensions#441 (proxy-sidecar permissive consistency).
    """
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="envoy-sidecar",
        mtlsMode="strict",
    )
    assert r.authBridgeMode == "envoy-sidecar"
    assert r.mtlsMode == "strict"


def test_create_agent_request_allows_envoy_with_permissive():
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="envoy-sidecar",
        mtlsMode="permissive",
    )
    assert r.authBridgeMode == "envoy-sidecar"
    assert r.mtlsMode == "permissive"


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


def test_finalize_shipwright_request_allows_full_matrix():
    """The Shipwright finalize boundary used to reject envoy-sidecar
    + non-disabled mtlsMode. Both have been lifted now that the
    operator + extensions support the full matrix."""
    from app.routers.agents import FinalizeShipwrightBuildRequest

    # Always allowed
    FinalizeShipwrightBuildRequest(authBridgeMode="proxy-sidecar", mtlsMode="strict")
    # Newly allowed
    FinalizeShipwrightBuildRequest(authBridgeMode="envoy-sidecar", mtlsMode="strict")
    FinalizeShipwrightBuildRequest(authBridgeMode="envoy-sidecar", mtlsMode="permissive")


def test_create_agent_request_default_mtls_mode_is_none():
    """Bare request → mtlsMode None → operator falls back to its default
    (disabled). Sending undefined on the wire keeps existing behavior
    byte-identical for users who haven't engaged the new feature.
    """
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(name="a", namespace="ns")
    assert r.mtlsMode is None


def test_create_agent_request_envoy_with_unset_mtls_mode():
    """envoy-sidecar with mtlsMode unset is the CLI / direct-API path
    (no mtlsMode on the wire → resolution chain falls through to the
    namespace ConfigMap or the operator default). Locks in that the
    validator doesn't gate on mtlsMode being present — only on its
    value when it IS present. Catches a regression if a future
    tightening accidentally rejects unset mtlsMode for envoy-sidecar.
    """
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a",
        namespace="ns",
        authBridgeMode="envoy-sidecar",
    )
    assert r.authBridgeMode == "envoy-sidecar"
    assert r.mtlsMode is None


def test_create_agent_request_unknown_mtls_value_rejected():
    """Pydantic Literal enforcement — any non-enum value is rejected
    at the API layer, before the validator runs.
    """
    from app.routers.agents import CreateAgentRequest

    with pytest.raises(ValidationError):
        CreateAgentRequest(name="a", namespace="ns", mtlsMode="loose")


# --- TLS bridge ---


def test_manifest_omits_tls_bridge_mode_when_unset():
    """Default (tls_bridge_enabled=False) → no spec.tlsBridgeMode key, so the
    operator default 'disabled' applies and envoy agents aren't webhook-rejected."""
    from app.routers.agents import _build_agentruntime_manifest

    m = _build_agentruntime_manifest("a", "ns", "deployment")
    assert "tlsBridgeMode" not in m["spec"]


def test_manifest_sets_tls_bridge_mode_when_enabled():
    """tls_bridge_enabled=True → spec.tlsBridgeMode == 'enabled'."""
    from app.routers.agents import _build_agentruntime_manifest

    m = _build_agentruntime_manifest("a", "ns", "deployment", tls_bridge_enabled=True)
    assert m["spec"]["tlsBridgeMode"] == "enabled"


def test_create_agent_request_rejects_tls_bridge_with_envoy():
    """The TLS bridge lives in the Go forward proxy, so enabling it with
    envoy-sidecar is rejected at the API layer (mirrors the operator webhook)."""
    from app.routers.agents import CreateAgentRequest

    with pytest.raises(ValidationError):
        CreateAgentRequest(
            name="a", namespace="ns", authBridgeMode="envoy-sidecar", tlsBridgeEnabled=True
        )


def test_create_agent_request_allows_tls_bridge_with_proxy_sidecar():
    """proxy-sidecar (and the empty default) accept tlsBridgeEnabled."""
    from app.routers.agents import CreateAgentRequest

    r = CreateAgentRequest(
        name="a", namespace="ns", authBridgeMode="proxy-sidecar", tlsBridgeEnabled=True
    )
    assert r.tlsBridgeEnabled is True
    # empty mode defaults to proxy-sidecar and is allowed
    r2 = CreateAgentRequest(name="a", namespace="ns", tlsBridgeEnabled=True)
    assert r2.tlsBridgeEnabled is True


def test_finalize_request_rejects_tls_bridge_with_envoy():
    """The same fast-422 must hold on the Shipwright finalize boundary, so a
    direct finalize call (or a stored-config combo) can't bypass it."""
    from app.routers.agents import FinalizeShipwrightBuildRequest

    with pytest.raises(ValidationError):
        FinalizeShipwrightBuildRequest(authBridgeMode="envoy-sidecar", tlsBridgeEnabled=True)


def test_finalize_request_allows_tls_bridge_with_proxy_sidecar():
    from app.routers.agents import FinalizeShipwrightBuildRequest

    r = FinalizeShipwrightBuildRequest(authBridgeMode="proxy-sidecar", tlsBridgeEnabled=True)
    assert r.tlsBridgeEnabled is True


# --- targetRef per workload type ---


def test_manifest_targetref_sandbox():
    """Sandbox is an agents.x-k8s.io CR, not apps/v1 — the targetRef must carry
    the Sandbox kind + group so the operator's resolveTargetRef binds the real
    workload (a wrong apps/v1 ref would dangle and never reconcile). Pairs with
    the backend un-excluding sandbox from _ensure_agentruntime."""
    from app.routers.agents import _build_agentruntime_manifest

    m = _build_agentruntime_manifest("a", "ns", "sandbox", tls_bridge_enabled=True)
    ref = m["spec"]["targetRef"]
    assert ref["kind"] == "Sandbox"
    assert ref["apiVersion"] == "agents.x-k8s.io/v1alpha1"
    assert ref["name"] == "a"
    # The AuthBridge knobs flow into the sandbox CR exactly like deployment.
    assert m["spec"]["tlsBridgeMode"] == "enabled"


def test_manifest_targetref_apps_v1_for_deployment_and_statefulset():
    """Regression: deployment/statefulset keep the apps/v1 targetRef. Locks the
    default branch of the per-kind apiVersion/kind maps so adding sandbox can't
    silently change the existing kinds."""
    from app.routers.agents import _build_agentruntime_manifest

    for wt, kind in (("deployment", "Deployment"), ("statefulset", "StatefulSet")):
        ref = _build_agentruntime_manifest("a", "ns", wt)["spec"]["targetRef"]
        assert ref["apiVersion"] == "apps/v1"
        assert ref["kind"] == kind
