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

import logging
import time
from typing import Optional

from app.services.sidecar_manager import SidecarObservation

logger = logging.getLogger(__name__)


class LooperAnalyzer:
    """Monitors session events and decides when to auto-continue the agent."""

    def __init__(self, counter_limit: int = 5) -> None:
        self.counter_limit = counter_limit
        self.continue_counter = 0
        self._observation_count = 0
        self._session_done = False
        self._waiting_hitl = False
        self._last_state: str = ""
        self._last_polled_state: str = ""  # Dedup: only trigger on state changes

    def ingest(self, event: dict) -> None:
        """Process an SSE event to track session state."""
        # Check top-level done signal
        if event.get("done"):
            logger.debug("Looper: received done signal")
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
            logger.debug(
                "Looper: state transition -> %s (iteration=%d/%d)",
                state,
                self.continue_counter,
                self.counter_limit,
            )

        # Detect HITL / INPUT_REQUIRED
        event_type = event_data.get("type", "")
        if event_type == "hitl_request" or state == "INPUT_REQUIRED":
            self._waiting_hitl = True
            self._session_done = False
            logger.info("Looper: session entered HITL/INPUT_REQUIRED, pausing")

        # Detect completion — only trigger on state CHANGE to avoid
        # re-triggering when DB poll returns the same COMPLETED state.
        if state in ("COMPLETED", "FAILED") and state != self._last_polled_state:
            self._session_done = True
            self._waiting_hitl = False
            self._last_polled_state = state
            logger.info(
                "Looper: session %s detected (iteration=%d/%d)",
                state,
                self.continue_counter,
                self.counter_limit,
            )
        elif state and state not in ("COMPLETED", "FAILED"):
            # Non-terminal state — reset polled state tracker
            self._last_polled_state = state

    def should_continue(self) -> bool:
        """Check if the agent should be auto-continued."""
        # Don't auto-continue if waiting on HITL
        if self._waiting_hitl:
            return False
        # Auto-continue if session completed (turn ended)
        if self._session_done:
            logger.debug(
                "Looper: should_continue check — done=%s, iteration=%d/%d",
                self._session_done,
                self.continue_counter,
                self.counter_limit,
            )
            return True
        return False

    def record_continue(self) -> SidecarObservation:
        """Record that auto-continue was sent. Returns an observation for the UI."""
        self.continue_counter += 1
        self._session_done = False  # Reset — wait for next completion
        self._last_polled_state = ""  # Reset dedup so next COMPLETED is detected
        self._observation_count += 1
        logger.debug(
            "Looper: record_continue — counter=%d/%d, reset _last_polled_state",
            self.continue_counter,
            self.counter_limit,
        )
        now = time.time()

        if self.continue_counter >= self.counter_limit:
            return SidecarObservation(
                id=f"looper-{self._observation_count}-{int(now)}",
                sidecar_type="looper",
                timestamp=now,
                message=(
                    f"Iteration limit reached: {self.continue_counter}/{self.counter_limit}. "
                    f"Paused — reset to continue."
                ),
                severity="critical",
                requires_approval=True,
            )

        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message=(
                f"Auto-continued agent. Iteration {self.continue_counter}/{self.counter_limit}."
            ),
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
                f"Iterations so far: {self.continue_counter}/{self.counter_limit}."
            ),
            severity="info",
        )

    def emit_limit_reached(self) -> SidecarObservation:
        """Emit observation when iteration limit is reached (without incrementing counter)."""
        self._observation_count += 1
        now = time.time()
        logger.info(
            "Looper: limit reached %d/%d — pausing",
            self.continue_counter,
            self.counter_limit,
        )
        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message=(
                f"Iteration limit reached: {self.continue_counter}/{self.counter_limit}. "
                f"Paused — approve to reset and continue."
            ),
            severity="critical",
            requires_approval=True,
        )

    def reset_counter(self) -> SidecarObservation:
        """Reset the iteration counter. Called via API or HITL approval."""
        self.continue_counter = 0
        self._session_done = False
        self._last_polled_state = ""  # Reset dedup so next COMPLETED is detected
        self._observation_count += 1
        logger.debug("Looper: reset_counter — dedup state cleared")
        now = time.time()
        return SidecarObservation(
            id=f"looper-{self._observation_count}-{int(now)}",
            sidecar_type="looper",
            timestamp=now,
            message="Counter reset. Looper will auto-continue on next completion.",
            severity="info",
        )
