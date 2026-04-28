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
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.services.sidecars.looper import LooperAnalyzer

logger = logging.getLogger(__name__)


def _safe_log(value: object) -> str:
    """Sanitize user input for logging (CWE-117 log injection prevention)."""
    s = str(value) if not isinstance(value, str) else value
    return s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")


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
    namespace: str = "team1"
    agent_name: str = "sandbox-legion"
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
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "auto_approve": self.auto_approve,
            "config": self.config,
            "observation_count": len(self.observations),
            "pending_count": len(self.pending_interventions),
            "created_at": self.created_at,
        }

    def to_persistable(self) -> dict:
        """Serialize sidecar state for DB persistence (excludes asyncio objects)."""
        return {
            "context_id": self.context_id,
            "sidecar_type": self.sidecar_type.value,
            "parent_context_id": self.parent_context_id,
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "auto_approve": self.auto_approve,
            "config": self.config,
            "observations": [
                {
                    "id": o.id,
                    "sidecar_type": o.sidecar_type,
                    "timestamp": o.timestamp,
                    "message": o.message,
                    "severity": o.severity,
                    "requires_approval": o.requires_approval,
                }
                for o in self.observations
            ],
            "pending_interventions": [
                {
                    "id": o.id,
                    "sidecar_type": o.sidecar_type,
                    "timestamp": o.timestamp,
                    "message": o.message,
                    "severity": o.severity,
                    "requires_approval": o.requires_approval,
                }
                for o in self.pending_interventions
            ],
            "created_at": self.created_at,
        }

    @classmethod
    def from_persisted(cls, data: dict) -> "SidecarHandle":
        """Restore a SidecarHandle from persisted state (no asyncio task)."""
        handle = cls(
            context_id=data.get("context_id", ""),
            sidecar_type=SidecarType(data["sidecar_type"]),
            parent_context_id=data.get("parent_context_id", ""),
            namespace=data.get("namespace", "team1"),
            agent_name=data.get("agent_name", "sandbox-legion"),
            enabled=data.get("enabled", False),
            auto_approve=data.get("auto_approve", False),
            config=data.get("config", {}),
            created_at=data.get("created_at", time.time()),
        )
        # Restore observations
        for o in data.get("observations", []):
            handle.observations.append(
                SidecarObservation(
                    id=o["id"],
                    sidecar_type=o["sidecar_type"],
                    timestamp=o["timestamp"],
                    message=o["message"],
                    severity=o.get("severity", "info"),
                    requires_approval=o.get("requires_approval", False),
                )
            )
        for o in data.get("pending_interventions", []):
            handle.pending_interventions.append(
                SidecarObservation(
                    id=o["id"],
                    sidecar_type=o["sidecar_type"],
                    timestamp=o["timestamp"],
                    message=o["message"],
                    severity=o.get("severity", "info"),
                    requires_approval=o.get("requires_approval", False),
                )
            )
        return handle


class SidecarManager:
    """
    Manages sidecar agent lifecycle for all active sessions.

    Registry: Dict[parent_context_id, Dict[SidecarType, SidecarHandle]]
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict[SidecarType, SidecarHandle]] = {}
        # Per-sidecar event queues: each sidecar gets its own queue so
        # Queue.get() in one sidecar doesn't steal events from another.
        # Fan-out happens in fan_out_event().

    def _get_or_create_queue(self, handle: "SidecarHandle") -> asyncio.Queue:
        """Get or create a per-sidecar event queue."""
        if handle.event_queue is None:
            handle.event_queue = asyncio.Queue(maxsize=1000)
        return handle.event_queue

    async def _persist_sidecar_state(self, parent_context_id: str) -> None:
        """Persist all sidecar handles for a session into the session's task metadata.

        Writes a ``sidecar_state`` key into the latest task row's metadata
        so that sidecar handles survive backend restarts.
        """
        session_sidecars = self._registry.get(parent_context_id, {})
        if not session_sidecars:
            return

        # Determine namespace from any handle
        namespace = next(iter(session_sidecars.values())).namespace

        state_to_persist = {
            st.value: handle.to_persistable() for st, handle in session_sidecars.items()
        }

        try:
            from app.services.session_db import get_session_pool

            pool = await get_session_pool(namespace)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                    parent_context_id,
                )
                if row:
                    meta = json.loads(row["metadata"]) if row["metadata"] else {}
                    meta["sidecar_state"] = state_to_persist
                    await conn.execute(
                        "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                        json.dumps(meta),
                        row["id"],
                    )
                    logger.debug(
                        "Persisted sidecar state for session %s (%d sidecars)",
                        _safe_log(parent_context_id[:12]),
                        len(state_to_persist),
                    )
        except Exception:
            logger.warning(
                "Failed to persist sidecar state for session %s",
                _safe_log(parent_context_id[:12]),
                exc_info=True,
            )

    async def _restore_sidecars_for_session(self, parent_context_id: str, namespace: str) -> None:
        """Restore sidecar handles from session metadata (on first access after restart).

        Reads ``sidecar_state`` from the latest task row's metadata and
        re-creates SidecarHandle objects (without spawning asyncio tasks —
        those are only spawned on explicit ``enable()``).
        """
        if parent_context_id in self._registry:
            return  # Already loaded

        try:
            from app.services.session_db import get_session_pool

            pool = await get_session_pool(namespace)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                    parent_context_id,
                )
                if not row or not row["metadata"]:
                    return

                meta = json.loads(row["metadata"]) if row["metadata"] else None
                if not isinstance(meta, dict):
                    return
                sidecar_state = meta.get("sidecar_state")
                if not sidecar_state:
                    return

                self._registry[parent_context_id] = {}
                for _type_str, handle_data in sidecar_state.items():
                    try:
                        handle = SidecarHandle.from_persisted(handle_data)
                        stype = SidecarType(handle_data["sidecar_type"])
                        # Don't auto-spawn tasks — user must re-enable
                        handle.enabled = False
                        handle.task = None
                        self._registry[parent_context_id][stype] = handle
                    except (ValueError, KeyError) as e:
                        logger.warning(
                            "Failed to restore sidecar %s for session %s: %s",
                            _safe_log(_type_str),
                            _safe_log(parent_context_id[:12]),
                            e,
                        )

                restored_count = len(self._registry[parent_context_id])
                if restored_count:
                    logger.info(
                        "Restored %d sidecars from DB for session %s",
                        restored_count,
                        _safe_log(parent_context_id[:12]),
                    )
        except Exception:
            logger.warning(
                "Failed to restore sidecars for session %s",
                _safe_log(parent_context_id[:12]),
                exc_info=True,
            )

    def fan_out_event(self, parent_context_id: str, event: dict) -> None:
        """Called by SSE proxy to fan out an event to all sidecars for a session.

        Each sidecar has its own queue, so events are delivered to all
        sidecars independently (no stealing).
        """
        session_sidecars = self._registry.get(parent_context_id, {})
        for handle in session_sidecars.values():
            if handle.enabled and handle.event_queue is not None:
                try:
                    handle.event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Event queue full for sidecar %s", handle.sidecar_type.value)

    async def enable(
        self,
        parent_context_id: str,
        sidecar_type: SidecarType,
        auto_approve: bool = False,
        config: Optional[dict] = None,
        namespace: str = "team1",
        agent_name: str = "sandbox-legion",
    ) -> SidecarHandle:
        """Enable a sidecar for a session. Spawns the asyncio task.

        Requires KAGENTI_FEATURE_FLAG_SIDECARS to be enabled.
        """
        from app.core.config import settings

        if not settings.kagenti_feature_flag_sidecars:
            raise RuntimeError(
                "Sidecars are disabled — set KAGENTI_FEATURE_FLAG_SIDECARS=true to enable"
            )

        # Restore any persisted state from DB on first access
        await self._restore_sidecars_for_session(parent_context_id, namespace)

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
            namespace=namespace,
            agent_name=agent_name,
            enabled=True,
            auto_approve=auto_approve,
            config=effective_config,
            event_queue=asyncio.Queue(maxsize=1000),
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
            _safe_log(sidecar_type.value),
            _safe_log(parent_context_id[:12]),
        )
        await self._persist_sidecar_state(parent_context_id)
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
            _safe_log(sidecar_type.value),
            _safe_log(parent_context_id[:12]),
        )
        await self._persist_sidecar_state(parent_context_id)

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
            _safe_log(sidecar_type.value),
            _safe_log(parent_context_id[:12]),
            _safe_log(config),
        )
        await self._persist_sidecar_state(parent_context_id)
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
                    _safe_log(msg_id),
                    _safe_log(sidecar_type.value),
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
                    _safe_log(msg_id),
                    _safe_log(sidecar_type.value),
                )
                return denied
        return None

    async def cleanup_session(self, parent_context_id: str) -> None:
        """Clean up all sidecars for a session (on session end)."""
        session_sidecars = self._registry.get(parent_context_id, {})
        # Persist final state before cleanup (preserves observations)
        if session_sidecars:
            await self._persist_sidecar_state(parent_context_id)
        for sidecar_type in list(session_sidecars.keys()):
            await self.disable(parent_context_id, sidecar_type)

        self._registry.pop(parent_context_id, None)
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
        """Looper: auto-continue agent when a turn completes.

        Watches for session completion events. When the agent finishes a turn,
        sends a "continue" message to keep it going. Tracks iterations and
        stops at the configurable limit, invoking HITL. Does NOT auto-continue
        when the session is waiting on HITL (INPUT_REQUIRED).
        """
        from .sidecars.looper import LooperAnalyzer

        analyzer = LooperAnalyzer(
            counter_limit=handle.config.get("counter_limit", 5),
        )
        interval = handle.config.get("interval_seconds", 10)

        logger.info(
            "Looper started: parent_context_id=%s namespace=%s agent=%s "
            "interval=%ds counter_limit=%d",
            handle.parent_context_id[:12],
            handle.namespace,
            handle.agent_name,
            interval,
            analyzer.counter_limit,
        )

        # Startup check: immediately query session state before the first
        # sleep interval. If the session already completed/failed before the
        # looper was enabled, set _session_done so the first iteration
        # triggers auto-continue instead of waiting interval_seconds.
        try:
            await self._poll_session_state(handle, analyzer)
            if analyzer._session_done:
                logger.info(
                    "Looper startup: session %s already %s — will auto-continue on first iteration",
                    handle.parent_context_id[:12],
                    analyzer._last_polled_state,
                )
        except Exception:
            logger.debug("Looper: startup session state poll failed (will retry in loop)")

        while handle.enabled:
            # Each iteration: read the current session state from the DB.
            # This is the primary detection mechanism — the looper doesn't
            # depend on SSE events. It polls the DB on a timer.
            try:
                await self._poll_session_state(handle, analyzer)
            except Exception:
                logger.debug("Looper: session state poll failed (will retry)")

            # Also drain any queued SSE events (supplementary — fast path)
            while handle.event_queue and not handle.event_queue.empty():
                try:
                    event = handle.event_queue.get_nowait()
                    analyzer.ingest(event)
                except asyncio.QueueEmpty:
                    break

            # Check if session is waiting on HITL
            hitl_obs = analyzer.hitl_status()
            if hitl_obs:
                # Only emit once per HITL wait
                if not handle.observations or handle.observations[-1].message != hitl_obs.message:
                    handle.observations.append(hitl_obs)

            # Check if we should auto-continue
            elif analyzer.should_continue():
                obs = analyzer.record_continue()
                handle.observations.append(obs)
                if obs.requires_approval:
                    # Limit reached — record_continue() already set severity/message
                    if handle.auto_approve:
                        reset_obs = analyzer.reset_counter()
                        handle.observations.append(reset_obs)
                        await self._send_continue(handle)
                    else:
                        handle.pending_interventions.append(obs)
                        logger.info("Looper: iteration limit reached, awaiting HITL")
                else:
                    await self._send_continue(handle)

            # Log iteration summary
            logger.debug(
                "Looper iteration: observations=%d pending=%d "
                "session_done=%s counter=%d/%d last_polled=%r",
                len(handle.observations),
                len(handle.pending_interventions),
                analyzer._session_done,
                analyzer.continue_counter,
                analyzer.counter_limit,
                analyzer._last_polled_state,
            )

            # Hot-reload config
            interval = handle.config.get("interval_seconds", 10)
            analyzer.counter_limit = handle.config.get("counter_limit", 5)

            await asyncio.sleep(interval)

    async def _poll_session_state(self, handle: SidecarHandle, analyzer: "LooperAnalyzer") -> None:
        """Read the latest session state from the DB and feed it to the analyzer.

        This runs every poll iteration. The analyzer tracks state internally
        and only triggers auto-continue when a COMPLETED/FAILED transition
        is detected (idempotent — repeated polls of the same state are no-ops).
        """
        import json

        try:
            from app.services.session_db import get_session_pool
        except ImportError:
            return

        pool = await get_session_pool(handle.namespace)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status FROM tasks WHERE context_id = $1"
                " ORDER BY COALESCE((status::json->>'timestamp')::text, '') DESC"
                " LIMIT 1",
                handle.parent_context_id,
            )
            if rows:
                status = json.loads(rows[0]["status"]) if rows[0]["status"] else {}
                state = status.get("state", "")
                logger.debug(
                    "Looper poll: context_id=%s namespace=%s state=%r "
                    "last_polled=%r session_done=%s",
                    handle.parent_context_id[:12],
                    handle.namespace,
                    state,
                    analyzer._last_polled_state,
                    analyzer._session_done,
                )
                if state:
                    # Feed state to analyzer — it handles dedup internally
                    analyzer.ingest({"result": {"status": {"state": state}}})
            else:
                logger.debug(
                    "Looper poll: no rows for context_id=%s namespace=%s",
                    handle.parent_context_id[:12],
                    handle.namespace,
                )

    async def _send_continue(self, handle: SidecarHandle) -> None:
        """Send a 'continue' message by creating a child session via A2A.

        Creates a new session (child) with ``parent_context_id`` set to the
        parent session's context_id.  This keeps iterations visible in the
        sub-sessions tab and avoids polluting the parent's context window.
        """
        import httpx
        from uuid import uuid4

        agent_url = f"http://{handle.agent_name}.{handle.namespace}.svc.cluster.local:8000"

        # Generate a new context_id for the child session
        child_context_id = uuid4().hex[:36]
        iteration_count = len([o for o in handle.observations if "Auto-continued" in o.message])

        a2a_msg = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": uuid4().hex,
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "continue"}],
                    "messageId": uuid4().hex,
                    "contextId": child_context_id,
                    "metadata": {
                        "source": "sidecar-looper",
                        "parent_context_id": handle.parent_context_id,
                        "iteration_count": iteration_count,
                    },
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{agent_url}/", json=a2a_msg)
                resp.raise_for_status()
                logger.info(
                    "Looper auto-continued session %s -> child %s (iteration %d)",
                    handle.parent_context_id[:12],
                    child_context_id[:12],
                    iteration_count,
                )

                # Write parent_context_id into the child session's metadata
                # so it appears in the sub-sessions tab
                await self._set_child_metadata(
                    handle.namespace,
                    child_context_id,
                    handle.parent_context_id,
                    iteration_count,
                )
        except Exception as e:
            logger.error(
                "Looper auto-continue failed for session %s: %s", handle.parent_context_id[:12], e
            )

    async def _set_child_metadata(
        self,
        namespace: str,
        child_context_id: str,
        parent_context_id: str,
        iteration_count: int,
    ) -> None:
        """Write parent_context_id into the child session's task metadata.

        Retries a few times because the task row may not exist yet when the
        A2A message/send returns synchronously.
        """
        import json

        try:
            from app.services.session_db import get_session_pool
        except ImportError:
            logger.warning("Cannot import get_session_pool for child metadata write")
            return

        for attempt in range(5):
            try:
                pool = await get_session_pool(namespace)
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT metadata FROM tasks WHERE context_id = $1 LIMIT 1",
                        child_context_id,
                    )
                    if not rows:
                        # Task row not yet created — wait and retry
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue

                    meta = json.loads(rows[0]["metadata"]) if rows[0]["metadata"] else {}
                    meta["parent_context_id"] = parent_context_id
                    meta["source"] = "sidecar-looper"
                    meta["title"] = f"Looper iteration {iteration_count}"
                    await conn.execute(
                        "UPDATE tasks SET metadata = $1::json WHERE context_id = $2",
                        json.dumps(meta),
                        child_context_id,
                    )
                    logger.info(
                        "Set parent_context_id on child session %s -> parent %s",
                        child_context_id[:12],
                        parent_context_id[:12],
                    )
                    return
            except Exception:
                logger.warning(
                    "Failed to set child metadata (attempt %d/5) for %s",
                    attempt + 1,
                    child_context_id[:12],
                    exc_info=True,
                )
                if attempt < 4:
                    await asyncio.sleep(1.0 * (attempt + 1))

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
