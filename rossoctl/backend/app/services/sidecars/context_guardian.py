# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Context Budget Guardian Sidecar Analyzer — warns on context growth.

Tracks token usage from SSE status events, maintains a trajectory
of tokens per turn, and emits warnings when growth rate is sharp
or thresholds are crossed.
"""

import time
from typing import Optional

from app.services.sidecar_manager import SidecarObservation


class ContextGuardianAnalyzer:
    """Analyzes SSE events for context budget issues."""

    def __init__(self, warn_pct: int = 60, critical_pct: int = 80) -> None:
        self.warn_pct = warn_pct
        self.critical_pct = critical_pct
        self._token_history: list[tuple[float, int]] = []  # (timestamp, token_count)
        self._tool_call_count = 0
        self._total_content_length = 0
        self._warned = False
        self._critical_warned = False
        self._observation_count = 0

    def analyze(self, event: dict) -> Optional[SidecarObservation]:
        """Analyze an SSE event for context budget issues."""
        event_data = event.get("event", event)
        event_type = event_data.get("type", "")

        # Track content accumulation
        if event_type in ("tool_result", "llm_response"):
            content = str(event_data.get("output", event_data.get("content", "")))
            self._total_content_length += len(content)

        if event_type == "tool_call":
            self._tool_call_count += 1

        # Check for token count in status events
        if event_type == "status":
            token_count = event_data.get("token_count", 0)
            if token_count > 0:
                self._token_history.append((time.time(), token_count))

        # Estimate context usage from content length (rough: 4 chars ~= 1 token)
        estimated_tokens = self._total_content_length // 4
        # Use a reasonable context window size (128K for Llama 4 Scout)
        max_tokens = 128000
        usage_pct = (estimated_tokens / max_tokens) * 100

        now = time.time()

        # Critical threshold
        if usage_pct >= self.critical_pct and not self._critical_warned:
            self._critical_warned = True
            self._observation_count += 1
            return SidecarObservation(
                id=f"guardian-{self._observation_count}-{int(now)}",
                sidecar_type="context_guardian",
                timestamp=now,
                message=(
                    f"Context usage CRITICAL: ~{usage_pct:.0f}% "
                    f"(~{estimated_tokens:,} tokens estimated from "
                    f"{self._total_content_length:,} chars, "
                    f"{self._tool_call_count} tool calls). "
                    f"Recommend: stop reading large files, compact conversation."
                ),
                severity="critical",
                requires_approval=True,
            )

        # Warning threshold
        if usage_pct >= self.warn_pct and not self._warned:
            self._warned = True
            self._observation_count += 1
            return SidecarObservation(
                id=f"guardian-{self._observation_count}-{int(now)}",
                sidecar_type="context_guardian",
                timestamp=now,
                message=(
                    f"Context usage WARNING: ~{usage_pct:.0f}% "
                    f"(~{estimated_tokens:,} tokens estimated, "
                    f"{self._tool_call_count} tool calls). "
                    f"Consider summarizing or reducing verbose output."
                ),
                severity="warning",
            )

        # Sharp growth detection: >10K chars in a single event
        if event_type == "tool_result":
            content = str(event_data.get("output", ""))
            if len(content) > 10000:
                self._observation_count += 1
                return SidecarObservation(
                    id=f"guardian-{self._observation_count}-{int(now)}",
                    sidecar_type="context_guardian",
                    timestamp=now,
                    message=(
                        f"Large tool output detected: {len(content):,} chars. "
                        f"This is consuming significant context budget."
                    ),
                    severity="info",
                )

        return None
