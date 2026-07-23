# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Dream-state watermark store (ConfigMap-backed).

Tracks, per (namespace, agent), the high-water mark of trajectories that have
already been "dreamed on", so a dream run only ever consumes NEW trajectories and
never re-processes ones a previous run already optimized.

Persisted in a single ConfigMap (``rossoctl-dream-state`` in rossoctl-system),
mirroring how skill auto-sync stores its status — no database is introduced.
Each agent is one JSON entry keyed ``"<namespace>/<agent>"``:

    {"last_dreamed_ts": "<ISO8601>", "last_dreamed_at": "...", "last_run_id": "...",
     "dreamed_count": N, "min_new_trajectories": 0, "min_interval_seconds": 0}

``last_dreamed_ts`` is the watermark: the start time of the newest trajectory a
run consumed. The next run only pulls trajectories newer than it.
"""

import datetime as _dt
import json
import logging
from typing import Dict, Optional

import kubernetes.client as k8s_client
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

DREAM_STATE_CM = "rossoctl-dream-state"
_ROSSOCTL_SYSTEM = "rossoctl-system"


def _key(namespace: str, agent_name: str) -> str:
    # ConfigMap data keys must match [-._a-zA-Z0-9]+ (no '/').
    return f"{namespace}.{agent_name}"


def _read_all(kube) -> Dict[str, dict]:
    """Return the full {key: state-dict} map from the ConfigMap ({} if absent)."""
    try:
        cm = kube.core_api.read_namespaced_config_map(
            name=DREAM_STATE_CM, namespace=_ROSSOCTL_SYSTEM
        )
    except ApiException as exc:
        if exc.status == 404:
            return {}
        raise
    out: Dict[str, dict] = {}
    for k, v in (cm.data or {}).items():
        try:
            out[k] = json.loads(v)
        except (ValueError, TypeError):
            out[k] = {}
    return out


def _write_entry(kube, namespace: str, agent_name: str, entry: dict) -> None:
    """Upsert one agent's state entry into the ConfigMap (create CM if needed)."""
    key = _key(namespace, agent_name)
    patch = {"data": {key: json.dumps(entry)}}
    try:
        kube.core_api.patch_namespaced_config_map(
            name=DREAM_STATE_CM, namespace=_ROSSOCTL_SYSTEM, body=patch
        )
    except ApiException as exc:
        if exc.status == 404:
            body = k8s_client.V1ConfigMap(
                metadata=k8s_client.V1ObjectMeta(
                    name=DREAM_STATE_CM,
                    namespace=_ROSSOCTL_SYSTEM,
                    labels={"rossoctl.io/type": "dream-state"},
                ),
                data={key: json.dumps(entry)},
            )
            kube.core_api.create_namespaced_config_map(namespace=_ROSSOCTL_SYSTEM, body=body)
        else:
            raise


def get_state(kube, namespace: str, agent_name: str) -> Optional[dict]:
    """Return the state dict for (namespace, agent), or None if never dreamed."""
    return _read_all(kube).get(_key(namespace, agent_name))


def get_cursor(kube, namespace: str, agent_name: str) -> Optional[str]:
    """Return the watermark ISO timestamp (last_dreamed_ts), or None."""
    state = get_state(kube, namespace, agent_name)
    return (state or {}).get("last_dreamed_ts")


def _max_ts(prev: Optional[str], new_ts: str) -> str:
    """Return the later of two ISO timestamps.

    Compares parsed datetimes so mixed offset forms (``Z`` vs ``+00:00``) order
    correctly; falls back to lexicographic order only if a value is unparseable.
    """
    if not prev:
        return new_ts
    try:
        prev_dt = _dt.datetime.fromisoformat(prev.replace("Z", "+00:00"))
        new_dt = _dt.datetime.fromisoformat(new_ts.replace("Z", "+00:00"))
    except ValueError:
        return max(prev, new_ts)
    return prev if prev_dt >= new_dt else new_ts


def set_pending_cursor(kube, namespace: str, agent_name: str, new_ts: str, run_id: str) -> None:
    """Record the watermark a submitted (not-yet-complete) run WOULD advance to.

    The watermark is only committed once the run reaches ``ready`` (see
    ``commit_pending_cursor``), so a run that later fails does not silently
    consume its trajectories — they are re-dreamed on the next run.
    """
    state = get_state(kube, namespace, agent_name) or {}
    state["pending_ts"] = new_ts
    state["pending_run_id"] = run_id
    _write_entry(kube, namespace, agent_name, state)


def commit_pending_cursor(kube, namespace: str, agent_name: str, run_id: str) -> bool:
    """Commit a completed run's pending watermark. Idempotent.

    No-op (returns False) unless there is a pending watermark for exactly
    ``run_id``. Never moves the mark backward (keeps the max of old/new).
    """
    state = get_state(kube, namespace, agent_name) or {}
    if not state.get("pending_ts") or state.get("pending_run_id") != run_id:
        return False
    state["last_dreamed_ts"] = _max_ts(state.get("last_dreamed_ts"), state["pending_ts"])
    state["last_dreamed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    state["last_run_id"] = run_id
    state["dreamed_count"] = int(state.get("dreamed_count", 0)) + 1
    state.pop("pending_ts", None)
    state.pop("pending_run_id", None)
    _write_entry(kube, namespace, agent_name, state)
    return True


def clear_pending_cursor(kube, namespace: str, agent_name: str, run_id: str) -> None:
    """Drop a failed run's pending watermark so its trajectories are re-dreamed."""
    state = get_state(kube, namespace, agent_name) or {}
    if state.get("pending_run_id") != run_id:
        return
    state.pop("pending_ts", None)
    state.pop("pending_run_id", None)
    _write_entry(kube, namespace, agent_name, state)


def set_thresholds(
    kube,
    namespace: str,
    agent_name: str,
    min_new_trajectories: int,
    min_interval_seconds: int,
    schedule_days: Optional[list] = None,
    schedule_time: str = "",
) -> None:
    """Persist auto-trigger thresholds (not evaluated automatically in v1).

    Supports two complementary triggers, both stored for the scheduler iteration:
      * a count trigger (``min_new_trajectories``) and/or interval
        (``min_interval_seconds``);
      * a weekly schedule — ``schedule_days`` (e.g. ``["sun", "mon"]``) at
        ``schedule_time`` (``"HH:MM"``, 24h, cluster-local).
    """
    state = get_state(kube, namespace, agent_name) or {}
    state["min_new_trajectories"] = int(min_new_trajectories)
    state["min_interval_seconds"] = int(min_interval_seconds)
    state["schedule_days"] = list(schedule_days or [])
    state["schedule_time"] = str(schedule_time or "")
    _write_entry(kube, namespace, agent_name, state)
