# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for _build_authbridge_runtime_yaml helper.

Emits the per-plugin schema authbridge expects — every plugin-
specific setting lives inside its own plugin entry under
pipeline.inbound.plugins[] or pipeline.outbound.plugins[].
Plugin-level defaults (audience_file, bypass_paths, identity
file paths) are applied by the authbridge binary itself; this
helper deliberately omits them.
"""

import yaml


def _plugin_config(cfg, direction, name):
    """Navigate pipeline.<direction>.plugins[<name>].config."""
    plugins = cfg["pipeline"][direction]["plugins"]
    for entry in plugins:
        if entry["name"] == name:
            return entry["config"]
    raise AssertionError(f"plugin {name!r} not found under pipeline.{direction}.plugins")


def test_build_authbridge_runtime_yaml_client_secret():
    """Default (non-SPIRE) config uses client-secret identity."""
    from app.routers.agents import _build_authbridge_runtime_yaml

    result = _build_authbridge_runtime_yaml(
        keycloak_url="http://keycloak:8080",
        realm="rossoctl",
        issuer="http://keycloak.example.com/realms/rossoctl",
        spire_enabled=False,
    )
    cfg = yaml.safe_load(result)

    # The backend no longer emits a top-level `mode:` — the operator
    # layers it on per workload from
    #   AgentRuntime.Spec.AuthBridgeMode → namespace ConfigMap →
    #   deprecated annotation → cluster default (proxy-sidecar).
    # Locking absence here so a future revert that re-pins
    # mode in _build_authbridge_runtime_yaml doesn't go unnoticed.
    assert "mode" not in cfg
    # Structural sanity: a future change that drops both `mode` and
    # `pipeline` (e.g., a botched refactor) would still pass the
    # negative assertion above. Pin the positive too.
    assert "pipeline" in cfg

    jwt = _plugin_config(cfg, "inbound", "jwt-validation")
    assert jwt["issuer"] == "http://keycloak.example.com/realms/rossoctl"
    # keycloak_url + keycloak_realm let jwt-validation derive jwks_url
    # from the INTERNAL keycloak URL (see rossocortex#383).
    # Pinning the full jwks_url was the pre-plugin-fix workaround; the
    # two hints are the supported contract now.
    assert jwt["keycloak_url"] == "http://keycloak:8080"
    assert jwt["keycloak_realm"] == "rossoctl"
    assert "jwks_url" not in jwt

    tok = _plugin_config(cfg, "outbound", "token-exchange")
    assert tok["keycloak_url"] == "http://keycloak:8080"
    assert tok["keycloak_realm"] == "rossoctl"
    assert tok["default_policy"] == "passthrough"
    assert tok["identity"]["type"] == "client-secret"
    # Without SPIRE, no top-level spiffe block is emitted; authbridge
    # leaves the in-process Provider unbuilt.
    assert "spiffe" not in cfg
    # client-secret identity has no JWT-SVID assertion path; jwt_audience
    # must NOT be emitted (it would be ignored but is misleading config).
    assert "jwt_audience" not in tok["identity"]

    # Plugin defaults are applied by the authbridge binary, not
    # emitted here. Asserting absence keeps the contract honest.
    assert "bypass_paths" not in jwt
    assert "audience_file" not in jwt
    assert "client_id_file" not in tok["identity"]
    assert "client_secret_file" not in tok["identity"]


def test_build_authbridge_runtime_yaml_spire_enabled():
    """SPIRE-enabled config maps to spiffe identity with jwt_audience."""
    from app.routers.agents import _build_authbridge_runtime_yaml

    result = _build_authbridge_runtime_yaml(
        keycloak_url="http://keycloak:8080",
        realm="rossoctl",
        issuer="http://keycloak.example.com/realms/rossoctl",
        spire_enabled=True,
    )
    cfg = yaml.safe_load(result)

    # Top-level spiffe block (empty mapping) signals authbridge to
    # construct the in-process SPIFFE provider. All fields default.
    assert "spiffe" in cfg
    assert cfg["spiffe"] == {}

    tok = _plugin_config(cfg, "outbound", "token-exchange")
    assert tok["identity"]["type"] == "spiffe"
    # JWT-SVID client-assertion audience — must equal the realm issuer
    # URL Keycloak's SPIFFE IdP expects. See rossocortex#332.
    assert tok["identity"]["jwt_audience"] == "http://keycloak.example.com/realms/rossoctl"
    # jwt_svid_path is not emitted — the plugin applies
    # /opt/jwt_svid.token as its default when identity.type is spiffe.
    assert "jwt_svid_path" not in tok["identity"]
