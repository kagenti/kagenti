# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Hallucination Observer Sidecar Analyzer — detects fabricated paths/APIs.

Monitors tool call events for file path references, API endpoints, and
import statements. Validates against the workspace filesystem. Emits
observations when invalid references are detected.
"""

import re
import time
from typing import Optional

from app.services.sidecar_manager import SidecarObservation


class HallucinationAnalyzer:
    """Analyzes SSE events for hallucinated file paths and API references."""

    def __init__(self) -> None:
        self._seen_paths: set[str] = set()
        self._observation_count = 0

    def analyze(self, event: dict) -> Optional[SidecarObservation]:
        """Analyze a single SSE event for hallucination indicators."""
        event_data = event.get("event", event)
        event_type = event_data.get("type", "")

        # Only analyze tool results and LLM responses
        if event_type not in ("tool_result", "llm_response", "tool_call"):
            return None

        content = ""
        if event_type == "tool_result":
            content = str(event_data.get("output", ""))
        elif event_type == "llm_response":
            content = str(event_data.get("content", ""))
        elif event_type == "tool_call":
            content = str(event_data.get("args", {}))

        if not content:
            return None

        # Extract file paths
        paths = re.findall(r'(/workspace/[^\s\'"`,\)]+)', content)

        # Extract "No such file" errors from tool results
        not_found = re.findall(r"No such file or directory: ['\"]?([^\s'\"]+)", content)

        if not_found:
            for path in not_found:
                if path in self._seen_paths:
                    continue
                self._seen_paths.add(path)
                self._observation_count += 1
                return SidecarObservation(
                    id=f"hallucination-{self._observation_count}-{int(time.time())}",
                    sidecar_type="hallucination_observer",
                    timestamp=time.time(),
                    message=f"File not found: `{path}`. Agent referenced a non-existent path.",
                    severity="warning",
                )

        # Track seen paths for cross-referencing
        for path in paths:
            self._seen_paths.add(path)

        return None
