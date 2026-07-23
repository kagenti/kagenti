# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for simulated-tool manifest building (issue #2161)."""

from app.core import constants
from app.services.simulation_manifests import (
    EnvVar,
    EnvVarSource,
    SecretKeyRef,
    build_simulation_env_vars,
)


def test_simulation_constants_exist():
    assert constants.ROSSOCTL_SIMULATED_LABEL == "rossoctl.io/simulated"
    assert constants.ROSSOCTL_AUTOSCALING_ANNOTATION == "rossoctl.io/autoscaling"
    assert constants.SIMULATION_HARNESS_SKILLS_MOUNT == "/app/skills-store"


def test_simulation_harness_image_setting_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.simulation_harness_image.startswith("ghcr.io/rossoctl/simulation-harness")


def test_simulation_image_pull_secret_setting_defaults():
    from app.core.config import Settings

    assert Settings().simulation_image_pull_secret == "ghcr-secret"


def test_env_vars_include_harness_and_platform_defaults():
    env = build_simulation_env_vars(None, port=8000)
    by_name = {e["name"]: e for e in env}
    assert by_name["HARNESS_SKILLS_FOLDER"]["value"] == "/app/skills-store"
    assert by_name["HARNESS_SERVER_PORT"]["value"] == "8000"
    assert by_name["HARNESS_SERVER_HOST"]["value"] == "0.0.0.0"
    # Opt back into boot-time autostart: the harness defaults it off, but Rossoctl
    # relies on it to resume the baked skill on Stop->Start and pod restarts.
    assert by_name["HARNESS_AUTOSTART_ENABLED"]["value"] == "true"
    # platform default preserved
    assert by_name["OTEL_EXPORTER_OTLP_ENDPOINT"]["value"].startswith("http://otel-collector")


def test_env_vars_expand_secret_key_ref():
    env = build_simulation_env_vars(
        [
            EnvVar(
                name="LLM_API_KEY",
                valueFrom=EnvVarSource(secretKeyRef=SecretKeyRef(name="llm-secret", key="api-key")),
            )
        ]
    )
    entry = next(e for e in env if e["name"] == "LLM_API_KEY")
    assert entry["valueFrom"]["secretKeyRef"] == {"name": "llm-secret", "key": "api-key"}


def test_env_vars_user_value_wins_on_dedupe():
    env = build_simulation_env_vars([EnvVar(name="HARNESS_SERVER_PORT", value="9999")])
    ports = [e for e in env if e["name"] == "HARNESS_SERVER_PORT"]
    assert len(ports) == 1
    assert ports[0]["value"] == "9999"


from app.services.simulation_manifests import build_simulation_statefulset


def _sts(**kw):
    defaults = {
        "name": "petstore",
        "namespace": "team1",
        "image": "ghcr.io/rossoctl/simulation-harness:latest",
        "env_vars": [{"name": "PORT", "value": "8000"}],
    }
    defaults.update(kw)
    return build_simulation_statefulset(**defaults)


def test_statefulset_core_shape():
    m = _sts()
    assert m["kind"] == "StatefulSet"
    assert m["spec"]["replicas"] == 1
    assert m["metadata"]["name"] == "petstore"
    assert m["metadata"]["namespace"] == "team1"
    c = m["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == "ghcr.io/rossoctl/simulation-harness:latest"
    assert c["ports"][0]["containerPort"] == 8000


def test_statefulset_labels_and_markers():
    m = _sts()
    labels = m["metadata"]["labels"]
    assert labels["protocol.rossoctl.io/mcp"] == ""
    assert labels["rossoctl.io/simulated"] == "true"
    assert labels["rossoctl.io/workload-type"] == "statefulset"
    assert labels["rossoctl.io/inject"] == "disabled"
    assert m["metadata"]["annotations"]["rossoctl.io/autoscaling"] == "disabled"
    # rossoctl.io/type must NOT be set on the workload by the backend — the
    # agent-label-protection VAP reserves that label for the operator, which
    # stamps it via the AgentRuntime CR. Guard both metadata and pod template.
    assert "rossoctl.io/type" not in labels
    assert "rossoctl.io/type" not in m["spec"]["template"]["metadata"]["labels"]


def test_statefulset_pvc_mounted_at_skills_dir():
    m = _sts(storage_size="2Gi")
    vct = m["spec"]["volumeClaimTemplates"][0]
    assert vct["metadata"]["name"] == "data"
    assert vct["spec"]["resources"]["requests"]["storage"] == "2Gi"
    mounts = m["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    data_mount = next(v for v in mounts if v["name"] == "data")
    assert data_mount["mountPath"] == "/app/skills-store"


def test_statefulset_probes_and_security_context():
    c = _sts()["spec"]["template"]["spec"]["containers"][0]
    assert c["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert c["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert c["securityContext"]["runAsUser"] == 1000
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_statefulset_spire_and_authbridge_flags():
    labels = _sts(spire_enabled=True, auth_bridge_enabled=True)["metadata"]["labels"]
    assert labels["rossoctl.io/spire"] == "enabled"
    assert labels["rossoctl.io/inject"] == "enabled"
    m = _sts(auth_bridge_mode="lite")
    pod_ann = m["spec"]["template"]["metadata"]["annotations"]
    assert pod_ann["rossoctl.io/authbridge-mode"] == "lite"


def test_statefulset_adds_image_pull_secret_when_provided():
    spec = _sts(image_pull_secret="ghcr-secret")["spec"]["template"]["spec"]
    assert spec["imagePullSecrets"] == [{"name": "ghcr-secret"}]


def test_statefulset_omits_image_pull_secret_when_none():
    spec = _sts()["spec"]["template"]["spec"]
    assert "imagePullSecrets" not in spec


def test_statefulset_omits_image_pull_secret_when_empty_string():
    spec = _sts(image_pull_secret="")["spec"]["template"]["spec"]
    assert "imagePullSecrets" not in spec


from app.services.simulation_manifests import build_simulation_service


def test_service_shape_and_labels():
    m = build_simulation_service("petstore", "team1", port=8000)
    assert m["kind"] == "Service"
    assert m["metadata"]["name"] == "petstore-mcp"
    assert m["spec"]["type"] == "ClusterIP"
    assert m["spec"]["selector"]["app.kubernetes.io/name"] == "petstore"
    assert m["spec"]["ports"][0]["port"] == 8000
    assert m["spec"]["ports"][0]["targetPort"] == 8000
    labels = m["metadata"]["labels"]
    assert labels["protocol.rossoctl.io/mcp"] == ""
    assert labels["rossoctl.io/simulated"] == "true"
    assert labels["rossoctl.io/type"] == "tool"


from app.services.simulation_manifests import build_simulation_agentruntime


def test_agentruntime_adopts_statefulset_as_tool():
    m = build_simulation_agentruntime("petstore", "team1")
    assert m["kind"] == "AgentRuntime"
    assert m["apiVersion"].endswith("/v1alpha1")
    assert m["metadata"]["name"] == "petstore"
    assert m["metadata"]["namespace"] == "team1"
    assert m["metadata"]["labels"]["rossoctl.io/simulated"] == "true"
    # Required CRD fields: type + targetRef pointing at the bare StatefulSet.
    assert m["spec"]["type"] == "tool"
    assert m["spec"]["targetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "name": "petstore",
    }
    # authBridgeMode only present when requested.
    assert "authBridgeMode" not in m["spec"]


def test_agentruntime_includes_authbridge_mode_when_set():
    m = build_simulation_agentruntime("petstore", "team1", auth_bridge_mode="lite")
    assert m["spec"]["authBridgeMode"] == "lite"


import pytest

from app.services.simulation_manifests import (
    derive_simulation_name,
    validate_openapi_spec,
)


def test_validate_spec_accepts_valid_json_object():
    spec = validate_openapi_spec(
        '{"openapi": "3.0.0", "info": {"title": "Pet Store"}, "paths": {}}'
    )
    assert spec["info"]["title"] == "Pet Store"


@pytest.mark.parametrize("bad", ["not json", "[]", '"a string"', "123", ""])
def test_validate_spec_rejects_non_object_or_invalid(bad):
    with pytest.raises(ValueError):
        validate_openapi_spec(bad)


def test_derive_name_prefers_requested():
    assert derive_simulation_name({"info": {"title": "Pet Store"}}, "my-sim") == "my-sim"


def test_derive_name_slugifies_title():
    assert (
        derive_simulation_name({"info": {"title": "Pet Store API v2!"}}, None) == "pet-store-api-v2"
    )


def test_derive_name_falls_back():
    assert derive_simulation_name({}, None) == "simulated-tool"


def test_statefulset_cache_emptydir_volume():
    m = _sts()
    mounts = m["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    cache_mount = next((v for v in mounts if v["name"] == "cache"), None)
    assert cache_mount is not None, "cache volumeMount not found"
    assert cache_mount["mountPath"] == "/app/.cache"

    volumes = m["spec"]["template"]["spec"]["volumes"]
    cache_vol = next((v for v in volumes if v["name"] == "cache"), None)
    assert cache_vol is not None, "cache volume not found"
    assert cache_vol["emptyDir"] == {}


def test_parity_simulation_matches_tool_identity_surface():
    """Guard: simulation StatefulSet must carry the same identity/mesh/security
    surface a tool StatefulSet does, so the standalone builders can't silently drift."""
    from app.routers.tools import _build_tool_statefulset_manifest
    from app.services.simulation_manifests import build_simulation_statefulset

    tool = _build_tool_statefulset_manifest(
        name="x",
        namespace="team1",
        image="img",
        framework="Python",
        auth_bridge_enabled=True,
        spire_enabled=True,
    )
    sim = build_simulation_statefulset(
        name="x",
        namespace="team1",
        image="img",
        env_vars=[],
        framework="Python",
        auth_bridge_enabled=True,
        spire_enabled=True,
    )
    mesh_keys = [
        "protocol.rossoctl.io/mcp",
        "rossoctl.io/transport",
        "rossoctl.io/framework",
        "rossoctl.io/inject",
        "rossoctl.io/spire",
    ]
    tl, sl = tool["metadata"]["labels"], sim["metadata"]["labels"]
    for k in mesh_keys:
        assert sl.get(k) == tl.get(k), f"identity label drift on {k}"
    tpc = tool["spec"]["template"]["spec"]
    spc = sim["spec"]["template"]["spec"]
    # Simulated tools add fsGroup so the uid-1000 harness can write its PVC;
    # apart from that PVC-driven divergence the pod securityContext must match
    # the regular tool identity surface.
    sim_sec = {k: v for k, v in spc["securityContext"].items() if k != "fsGroup"}
    assert sim_sec == tpc["securityContext"]
    assert spc["securityContext"].get("fsGroup") == 1000
    assert spc["containers"][0]["securityContext"] == tpc["containers"][0]["securityContext"]


from app.services.simulation_manifests import (
    MAX_SIMULATION_NAME_LEN,
    validate_custom_name,
    validate_namespace,
    validate_storage_size,
)


class TestInputValidators:
    def test_valid_namespace_passes(self):
        assert validate_namespace("team1") == "team1"
        assert validate_namespace("a-b-9") == "a-b-9"

    @pytest.mark.parametrize(
        "bad", ["Team1", "team_1", "-team", "team-", "team 1", "team\n1", "", "a" * 64]
    )
    def test_invalid_namespace_raises(self, bad):
        with pytest.raises(ValueError):
            validate_namespace(bad)

    @pytest.mark.parametrize("good", ["1Gi", "500Mi", "2G", "10Ti", "1024Ki"])
    def test_valid_storage_size_passes(self, good):
        assert validate_storage_size(good) == good

    @pytest.mark.parametrize("bad", ["big", "1gb", "Gi", "0Gi", "-1Gi", "1.Gi", "1 Gi", ""])
    def test_invalid_storage_size_raises(self, bad):
        with pytest.raises(ValueError):
            validate_storage_size(bad)

    def test_valid_custom_name_passes(self):
        assert validate_custom_name("pet-store") == "pet-store"

    @pytest.mark.parametrize("bad", ["Pet Store", "pet_store", "-x", "x-", "", "UPPER"])
    def test_invalid_custom_name_raises(self, bad):
        with pytest.raises(ValueError):
            validate_custom_name(bad)

    def test_custom_name_too_long_for_service_suffix_raises(self):
        # A name longer than MAX_SIMULATION_NAME_LEN would make "{name}-mcp" exceed 63.
        with pytest.raises(ValueError):
            validate_custom_name("a" * (MAX_SIMULATION_NAME_LEN + 1))
        assert validate_custom_name("a" * MAX_SIMULATION_NAME_LEN)


def test_derive_name_truncates_to_service_safe_length():
    name = derive_simulation_name({"info": {"title": "x" * 100}}, None)
    assert len(name) <= MAX_SIMULATION_NAME_LEN
    assert not name.endswith("-")
