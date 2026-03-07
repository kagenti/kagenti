# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Looper Sidecar Analyzer — detects stuck loops in sandbox agent sessions.

Monitors tool call patterns for repetition: same tool with same args,
identical error-retry cycles, oscillating states. Emits observations
and triggers HITL when counter limit is reached.
"""

import hashlib
import time
from collections import Counter
from typing import Optional

from app.services.sidecar_manager import SidecarObservation


class LooperAnalyzer:
    """Analyzes event streams for loop patterns."""

    def __init__(self, counter_limit: int = 3) -> None:
        self.counter_limit = counter_limit
        self._tool_call_hashes: list[str] = []
        self._loop_counter = 0
        self._last_observation_time = 0.0
        self._observation_count = 0

    def ingest(self, event: dict) -> None:
        """Ingest an SSE event and track tool call patterns."""
        event_data = event.get("event", event)
        event_type = event_data.get("type", "")

        if event_type == "tool_call":
            # Hash the tool name + args for dedup detection
            tool_name = event_data.get("name", "")
            tool_args = str(event_data.get("args", {}))
            call_hash = hashlib.md5(f"{tool_name}:{tool_args}".encode()).hexdigest()[:8]
            self._tool_call_hashes.append(call_hash)

            # Keep sliding window of last 20 calls
            if len(self._tool_call_hashes) > 20:
                self._tool_call_hashes = self._tool_call_hashes[-20:]

    def check(self) -> Optional[SidecarObservation]:
        """Check for loop patterns. Called periodically by the Looper task."""
        if len(self._tool_call_hashes) < 2:
            return None

        # Count repeated consecutive calls
        counts = Counter(self._tool_call_hashes[-10:])
        most_common_hash, most_common_count = counts.most_common(1)[0]

        # Detect: same tool call repeated 3+ times in last 10
        if most_common_count >= 3:
            self._loop_counter += 1
            self._observation_count += 1

            now = time.time()
            obs_id = f"looper-{self._observation_count}-{int(now)}"

            if self._loop_counter >= self.counter_limit:
                # Counter limit reached — trigger HITL
                return SidecarObservation(
                    id=obs_id,
                    sidecar_type="looper",
                    timestamp=now,
                    message=(
                        f"Agent stuck in loop: same tool call repeated "
                        f"{most_common_count}x in last 10 calls. "
                        f"Loop counter: {self._loop_counter}/{self.counter_limit}. "
                        f"Reset counter or send corrective message."
                    ),
                    severity="critical",
                    requires_approval=True,
                )

            return SidecarObservation(
                id=obs_id,
                sidecar_type="looper",
                timestamp=now,
                message=(
                    f"Detected repeated tool call pattern "
                    f"({most_common_count}x in last 10 calls). "
                    f"Loop counter: {self._loop_counter}/{self.counter_limit}."
                ),
                severity="warning",
            )

        # Also detect alternating patterns (A-B-A-B)
        if len(self._tool_call_hashes) >= 6:
            recent = self._tool_call_hashes[-6:]
            if (
                recent[0] == recent[2] == recent[4]
                and recent[1] == recent[3] == recent[5]
                and recent[0] != recent[1]
            ):
                self._loop_counter += 1
                self._observation_count += 1
                now = time.time()
                obs_id = f"looper-{self._observation_count}-{int(now)}"

                return SidecarObservation(
                    id=obs_id,
                    sidecar_type="looper",
                    timestamp=now,
                    message=(
                        "Detected oscillating tool call pattern (A-B-A-B). "
                        f"Loop counter: {self._loop_counter}/{self.counter_limit}."
                    ),
                    severity="warning",
                    requires_approval=self._loop_counter >= self.counter_limit,
                )

        return None

    def reset_counter(self) -> None:
        """Reset the loop counter (called via API or HITL approval)."""
        self._loop_counter = 0
