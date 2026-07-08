# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Unit tests for simulated-tool manifest building (issue #2161)."""

from app.core import constants


def test_simulation_constants_exist():
    assert constants.KAGENTI_SIMULATED_LABEL == "kagenti.io/simulated"
    assert constants.KAGENTI_AUTOSCALING_ANNOTATION == "kagenti.io/autoscaling"
    assert constants.SIMULATION_HARNESS_SKILLS_MOUNT == "/app/skills-store"


def test_simulation_harness_image_setting_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.simulation_harness_image.startswith("ghcr.io/kagenti/simulation-harness")
