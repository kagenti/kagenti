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
    assert constants.KAGENTI_SIMULATED_LABEL == "kagenti.io/simulated"
    assert constants.KAGENTI_AUTOSCALING_ANNOTATION == "kagenti.io/autoscaling"
    assert constants.SIMULATION_HARNESS_SKILLS_MOUNT == "/app/skills-store"


def test_simulation_harness_image_setting_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.simulation_harness_image.startswith("ghcr.io/kagenti/simulation-harness")


def test_env_vars_include_harness_and_platform_defaults():
    env = build_simulation_env_vars(None, port=8000)
    by_name = {e["name"]: e for e in env}
    assert by_name["HARNESS_SKILLS_FOLDER"]["value"] == "/app/skills-store"
    assert by_name["HARNESS_SERVER_PORT"]["value"] == "8000"
    assert by_name["HARNESS_SERVER_HOST"]["value"] == "0.0.0.0"
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
        "image": "ghcr.io/kagenti/simulation-harness:latest",
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
    assert c["image"] == "ghcr.io/kagenti/simulation-harness:latest"
    assert c["ports"][0]["containerPort"] == 8000


def test_statefulset_labels_and_markers():
    labels = _sts()["metadata"]["labels"]
    assert labels["protocol.kagenti.io/mcp"] == ""
    assert labels["kagenti.io/type"] == "tool"
    assert labels["kagenti.io/simulated"] == "true"
    assert labels["kagenti.io/workload-type"] == "statefulset"
    assert labels["kagenti.io/inject"] == "disabled"
    assert _sts()["metadata"]["annotations"]["kagenti.io/autoscaling"] == "disabled"


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
    assert labels["kagenti.io/spire"] == "enabled"
    assert labels["kagenti.io/inject"] == "enabled"
    m = _sts(auth_bridge_mode="lite")
    pod_ann = m["spec"]["template"]["metadata"]["annotations"]
    assert pod_ann["kagenti.io/authbridge-mode"] == "lite"
