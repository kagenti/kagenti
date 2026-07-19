# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for _extract_labels simulated-marker surfacing (#2165)."""

from app.routers.tools import _extract_labels
from app.core.constants import ROSSOCTL_SIMULATED_LABEL


class TestExtractLabelsSimulated:
    def test_simulated_true_when_marker_present(self):
        result = _extract_labels({ROSSOCTL_SIMULATED_LABEL: "true"})
        assert result.simulated is True

    def test_simulated_false_when_marker_absent(self):
        result = _extract_labels({"rossoctl.io/framework": "python"})
        assert result.simulated is False

    def test_simulated_false_when_marker_not_true(self):
        result = _extract_labels({ROSSOCTL_SIMULATED_LABEL: "false"})
        assert result.simulated is False

    def test_existing_fields_still_extracted(self):
        result = _extract_labels(
            {"protocol.rossoctl.io/mcp": "", "rossoctl.io/framework": "python"}
        )
        assert result.protocol == ["mcp"]
        assert result.framework == "python"
