# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
SidecarManager — manages sidecar agent lifecycle for sandbox sessions.

Sidecars are system sub-agents that observe parent sessions and intervene
when problems are detected (stuck loops, hallucinations, context bloat).

Each sidecar runs as an asyncio.Task in-process, consumes events from the
parent session's SSE stream (via asyncio.Queue), and has its own LangGraph
checkpointed state for persistence across restarts.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SidecarType(str, Enum):
    LOOPER = "looper"
    HALLUCINATION_OBSERVER = "hallucination_observer"
    CONTEXT_GUARDIAN = "context_guardian"


# Default configs per sidecar type
SIDECAR_DEFAULTS: dict[SidecarType, dict[str, Any]] = {
    SidecarType.LOOPER: {
        "interval_seconds": 30,
        "counter_limit": 3,
    },
    SidecarType.HALLUCINATION_OBSERVER: {},
    SidecarType.CONTEXT_GUARDIAN: {
        "warn_threshold_pct": 60,
        "critical_threshold_pct": 80,
    },
}


@dataclass
class SidecarObservation:
    """A single observation emitted by a sidecar."""

    id: str
    sidecar_type: str
    timestamp: float
    message: str
    severity: str = "info"  # info, warning, critical
    requires_approval: bool = False


@dataclass
class SidecarHandle:
    """Tracks a running sidecar's state."""

    task: Optional[asyncio.Task] = None
    context_id: str = ""
    sidecar_type: SidecarType = SidecarType.LOOPER
    parent_context_id: str = ""
    enabled: bool = False
    auto_approve: bool = False
    config: dict = field(default_factory=dict)
    observations: list[SidecarObservation] = field(default_factory=list)
    pending_interventions: list[SidecarObservation] = field(default_factory=list)
    event_queue: Optional[asyncio.Queue] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "context_id": self.context_id,
            "sidecar_type": self.sidecar_type.value,
            "parent_context_id": self.parent_context_id,
            "enabled": self.enabled,
            "auto_approve": self.auto_approve,
            "config": self.config,
            "observation_count": len(self.observations),
            "pending_count": len(self.pending_interventions),
            "created_at": self.created_at,
        }


class SidecarManager:
    """
    Manages sidecar agent lifecycle for all active sessions.

    Registry: Dict[parent_context_id, Dict[SidecarType, SidecarHandle]]
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict[SidecarType, SidecarHandle]] = {}
        # Per-session event queues: parent_context_id -> Queue
        self._session_queues: dict[str, asyncio.Queue] = {}

    def get_session_queue(self, parent_context_id: str) -> asyncio.Queue:
        """Get or create the event queue for a session. SSE proxy fans out to this."""
        if parent_context_id not in self._session_queues:
            self._session_queues[parent_context_id] = asyncio.Queue(maxsize=1000)
        return self._session_queues[parent_context_id]

    def fan_out_event(self, parent_context_id: str, event: dict) -> None:
        """Called by SSE proxy to fan out an event to all sidecars for a session."""
        queue = self._session_queues.get(parent_context_id)
        if queue is None:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "Event queue full for session %s, dropping event",
                parent_context_id[:12],
            )

    async def enable(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
        auto_approve: bool = False,
        config: Optional[dict] = None,
    ) -> SidecarHandle:
        """Enable a sidecar for a session. Spawns the asyncio task."""
        if parent_context_id not in self._registry:
            self._registry[parent_context_id] = {}

        session_sidecars = self._registry[parent_context_id]

        # If already enabled, return existing
        if sidecar_type in session_sidecars and session_sidecars[sidecar_type].enabled:
            return session_sidecars[sidecar_type]

        # Build config with defaults
        effective_config = {**SIDECAR_DEFAULTS.get(sidecar_type, {})}
        if config:
            effective_config.update(config)

        context_id = f"sidecar-{sidecar_type.value}-{parent_context_id[:12]}"

        handle = SidecarHandle(
            context_id=context_id,
            sidecar_type=sidecar_type,
            parent_context_id=parent_context_id,
            enabled=True,
            auto_approve=auto_approve,
            config=effective_config,
            event_queue=self.get_session_queue(parent_context_id),
        )

        # Restore observations from previous enable (if any)
        old_handle = session_sidecars.get(sidecar_type)
        if old_handle:
            handle.observations = old_handle.observations
            handle.pending_interventions = old_handle.pending_interventions

        # Spawn the sidecar task
        handle.task = asyncio.create_task(
            self._run_sidecar(handle),
            name=f"sidecar-{sidecar_type.value}-{parent_context_id[:8]}",
        )

        session_sidecars[sidecar_type] = handle
        logger.info(
            "Enabled sidecar %s for session %s",
            sidecar_type.value,
            parent_context_id[:12],
        )
        return handle

    async def disable(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
    ) -> None:
        """Disable a sidecar. Cancels the asyncio task, preserves observations."""
        session_sidecars = self._registry.get(parent_context_id, {})
        handle = session_sidecars.get(sidecar_type)
        if handle is None:
            return

        if handle.task and not handle.task.done():
            handle.task.cancel()
            try:
                await handle.task
            except asyncio.CancelledError:
                pass

        handle.enabled = False
        handle.task = None
        logger.info(
            "Disabled sidecar %s for session %s",
            sidecar_type.value,
            parent_context_id[:12],
        )

    async def update_config(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
        config: dict,
    ) -> SidecarHandle:
        """Update a sidecar's config. Hot-reloads into running task."""
        session_sidecars = self._registry.get(parent_context_id, {})
        handle = session_sidecars.get(sidecar_type)
        if handle is None:
            raise ValueError(f"Sidecar {sidecar_type.value} not found for session")

        handle.config.update(config)
        if "auto_approve" in config:
            handle.auto_approve = config["auto_approve"]

        logger.info(
            "Updated config for sidecar %s session %s: %s",
            sidecar_type.value,
            parent_context_id[:12],
            config,
        )
        return handle

    def list_sidecars(self, parent_context_id: str) -> list[dict]:
        """List all sidecars for a session."""
        session_sidecars = self._registry.get(parent_context_id, {})
        return [handle.to_dict() for handle in session_sidecars.values()]

    def get_handle(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
    ) -> Optional[SidecarHandle]:
        """Get a sidecar handle."""
        return self._registry.get(parent_context_id, {}).get(sidecar_type)

    def get_observations(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
    ) -> list[SidecarObservation]:
        """Get all observations for a sidecar."""
        handle = self.get_handle(parent_context_id, sidecar_type)
        if handle is None:
            return []
        return handle.observations

    async def approve_intervention(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
        msg_id: str,
    ) -> Optional[SidecarObservation]:
        """Approve a pending HITL intervention."""
        handle = self.get_handle(parent_context_id, sidecar_type)
        if handle is None:
            return None

        for i, obs in enumerate(handle.pending_interventions):
            if obs.id == msg_id:
                approved = handle.pending_interventions.pop(i)
                # TODO: inject corrective message into parent session via A2A
                logger.info(
                    "Approved intervention %s from %s",
                    msg_id,
                    sidecar_type.value,
                )
                return approved
        return None

    async def deny_intervention(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
        msg_id: str,
    ) -> Optional[SidecarObservation]:
        """Deny a pending HITL intervention."""
        handle = self.get_handle(parent_context_id, sidecar_type)
        if handle is None:
            return None

        for i, obs in enumerate(handle.pending_interventions):
            if obs.id == msg_id:
                denied = handle.pending_interventions.pop(i)
                logger.info(
                    "Denied intervention %s from %s",
                    msg_id,
                    sidecar_type.value,
                )
                return denied
        return None

    async def cleanup_session(self, parent_context_id: str) -> None:
        """Clean up all sidecars for a session (on session end)."""
        session_sidecars = self._registry.get(parent_context_id, {})
        for sidecar_type in list(session_sidecars.keys()):
            await self.disable(parent_context_id, sidecar_type)

        self._registry.pop(parent_context_id, None)
        self._session_queues.pop(parent_context_id, None)
        logger.info("Cleaned up sidecars for session %s", parent_context_id[:12])

    async def shutdown(self) -> None:
        """Cancel all sidecar tasks on backend shutdown."""
        for parent_context_id in list(self._registry.keys()):
            await self.cleanup_session(parent_context_id)
        logger.info("SidecarManager shutdown complete")

    # ── Internal: sidecar task runner ─────────────────────────────────────

    async def _run_sidecar(self, handle: SidecarHandle) -> None:
        """Main loop for a sidecar asyncio task. Dispatches to type-specific logic."""
        try:
            if handle.sidecar_type == SidecarType.LOOPER:
                await self._run_looper(handle)
            elif handle.sidecar_type == SidecarType.HALLUCINATION_OBSERVER:
                await self._run_hallucination_observer(handle)
            elif handle.sidecar_type == SidecarType.CONTEXT_GUARDIAN:
                await self._run_context_guardian(handle)
        except asyncio.CancelledError:
            logger.info(
                "Sidecar %s cancelled for session %s",
                handle.sidecar_type.value,
                handle.parent_context_id[:12],
            )
        except Exception:
            logger.exception(
                "Sidecar %s crashed for session %s",
                handle.sidecar_type.value,
                handle.parent_context_id[:12],
            )

    async def _run_looper(self, handle: SidecarHandle) -> None:
        """Looper: periodic timer, reads parent events, detects repeated patterns."""
        from .sidecars.looper import LooperAnalyzer

        analyzer = LooperAnalyzer(
            counter_limit=handle.config.get("counter_limit", 3),
        )
        interval = handle.config.get("interval_seconds", 30)

        while handle.enabled:
            await asyncio.sleep(interval)

            # Drain any queued events
            events = []
            while handle.event_queue and not handle.event_queue.empty():
                try:
                    events.append(handle.event_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Analyze accumulated events
            for event in events:
                analyzer.ingest(event)

            observation = analyzer.check()
            if observation:
                handle.observations.append(observation)
                if observation.requires_approval:
                    if handle.auto_approve:
                        # TODO: inject corrective message
                        logger.info("Looper auto-approved intervention")
                    else:
                        handle.pending_interventions.append(observation)
                        logger.info("Looper HITL: pending approval")

            # Re-read config (hot-reload)
            interval = handle.config.get("interval_seconds", 30)
            analyzer.counter_limit = handle.config.get("counter_limit", 3)

    async def _run_hallucination_observer(self, handle: SidecarHandle) -> None:
        """Hallucination Observer: SSE-driven, validates paths/APIs against workspace."""
        from .sidecars.hallucination_observer import HallucinationAnalyzer

        analyzer = HallucinationAnalyzer()

        while handle.enabled:
            if handle.event_queue is None:
                await asyncio.sleep(1)
                continue

            try:
                event = await asyncio.wait_for(handle.event_queue.get(), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                continue

            observation = analyzer.analyze(event)
            if observation:
                handle.observations.append(observation)

    async def _run_context_guardian(self, handle: SidecarHandle) -> None:
        """Context Guardian: SSE-driven, tracks token usage trajectory."""
        from .sidecars.context_guardian import ContextGuardianAnalyzer

        analyzer = ContextGuardianAnalyzer(
            warn_pct=handle.config.get("warn_threshold_pct", 60),
            critical_pct=handle.config.get("critical_threshold_pct", 80),
        )

        while handle.enabled:
            if handle.event_queue is None:
                await asyncio.sleep(1)
                continue

            try:
                event = await asyncio.wait_for(handle.event_queue.get(), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                continue

            observation = analyzer.analyze(event)
            if observation:
                handle.observations.append(observation)
                if observation.requires_approval:
                    if handle.auto_approve:
                        logger.info("Guardian auto-approved intervention")
                    else:
                        handle.pending_interventions.append(observation)

            # Hot-reload thresholds
            analyzer.warn_pct = handle.config.get("warn_threshold_pct", 60)
            analyzer.critical_pct = handle.config.get("critical_threshold_pct", 80)


# Singleton instance
_manager: Optional[SidecarManager] = None


def get_sidecar_manager() -> SidecarManager:
    """Get the global SidecarManager singleton."""
    global _manager
    if _manager is None:
        _manager = SidecarManager()
    return _manager
