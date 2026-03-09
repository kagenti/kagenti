# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Looper Sidecar — auto-continue for sandbox agent sessions.

When an agent completes a turn but the task isn't finished, the Looper
sends a "continue" message to resume the agent. It tracks the number
of iterations and pauses when the configurable limit is reached,
invoking HITL for the user to decide whether to continue.

The Looper does NOT resume when the session is waiting on HITL (INPUT_REQUIRED).
"""

import time
from typing import Optional

from app.services.sidecar_manager import SidecarObservation


class LooperAnalyzer:
    """Monitors session events and decides when to auto-continue the agent."""

    def __init__(self, counter_limit: int = 5) -> None:
        self.counter_limit = counter_limit
        self.kick_counter = 0
        self._observation_count = 0
        self._session_done = False
        self._waiting_hitl = False
        self._last_state: str = ""

    def ingest(self, event: dict) -> None:
        """Process an SSE event to track session state."""
        # Check top-level done signal
        if event.get("done"):
            self._session_done = True
            return

        event_data = event.get("event", event)
        result = event.get("result", {})

        # Check for task status in result
        status = result.get("status", {})
        state = status.get("state", "")
        if not state:
            state = event_data.get("state", "")

        if state:
            self._last_state = state

        # Detect HITL / INPUT_REQUIRED
        event_type = event_data.get("type", "")
        if event_type == "hitl_request" or state == "INPUT_REQUIRED":
            self._waiting_hitl = True
            self._session_done = False

        # Detect completion
        if state in ("COMPLETED", "FAILED"):
            self._session_done = True
            self._waiting_hitl = False

    def should_kick(self) -> bool:
        """Check if the agent should be auto-continued."""
        # Don't kick if waiting on HITL
        if self._waiting_hitl:
            return False
        # Kick if session completed (turn ended) and we haven't hit the limit
        if self._session_done and self.kick_counter < self.counter_limit:
            return True
        return False

    def record_kick(self) -> SidecarObservation:
        """Record that auto-continue was sent. Returns an observation for the UI."""
        self.kick_counter += 1
        self._session_done = False  # Reset — wait for next completion
        self._observation_count += 1
        now = time.time()

        if self.kick_counter >= self.counter_limit:
            return SidecarObservation(
                id=f"looper-{self._observation_count}-{int(now)}",
                sidecar_type="looper",
                timestamp=now,
                message=(
                    f"Iteration limit reached: {self.kick_counter}/{self.counter_limit}. "
                    f"Paused — reset to continue."
                ),
                severity="critical",
                requires_approval=True,
            )

        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message=(f"Auto-continued agent. Iteration {self.kick_counter}/{self.counter_limit}."),
            severity="info",
        )

    def hitl_status(self) -> Optional[SidecarObservation]:
        """Emit observation when session is waiting on HITL (paused)."""
        if not self._waiting_hitl:
            return None
        self._observation_count += 1
        now = time.time()
        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message=(
                f"Session waiting on HITL approval. Looper paused. "
                f"Iterations so far: {self.kick_counter}/{self.counter_limit}."
            ),
            severity="info",
        )

    def reset_counter(self) -> SidecarObservation:
        """Reset the iteration counter. Called via API or HITL approval."""
        self.kick_counter = 0
        self._session_done = False
        self._observation_count += 1
        now = time.time()
        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message="Counter reset. Looper will auto-continue on next completion.",
            severity="info",
        )
