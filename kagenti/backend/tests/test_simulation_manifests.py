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
