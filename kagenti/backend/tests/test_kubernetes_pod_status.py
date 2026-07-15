# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for KubernetesService.get_workload_pod_status (issue #2162)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from kubernetes.client import ApiException

from app.services.kubernetes import KubernetesService


def _pod(ready=False, waiting_reason=None, waiting_message=None):
    conditions = [SimpleNamespace(type="Ready", status="True" if ready else "False")]
    waiting = (
        SimpleNamespace(reason=waiting_reason, message=waiting_message)
        if waiting_reason is not None
        else None
    )
    container = SimpleNamespace(state=SimpleNamespace(waiting=waiting))
    return SimpleNamespace(
        status=SimpleNamespace(conditions=conditions, container_statuses=[container])
    )


def _svc_with_pods(pods):
    svc = KubernetesService.__new__(KubernetesService)  # bypass __init__
    core = MagicMock()
    core.list_namespaced_pod.return_value = SimpleNamespace(items=pods)
    svc._core_api = core  # see note in Step 3 about the accessor
    return svc, core


def test_ready_pod_reports_ready_no_waiting():
    svc, _ = _svc_with_pods([_pod(ready=True)])
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result == {"ready": True, "waiting_reason": None, "waiting_message": None}


def test_crashloop_pod_reports_waiting_reason():
    svc, _ = _svc_with_pods(
        [_pod(ready=False, waiting_reason="CrashLoopBackOff", waiting_message="back-off 5m")]
    )
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result["ready"] is False
    assert result["waiting_reason"] == "CrashLoopBackOff"
    assert result["waiting_message"] == "back-off 5m"


def test_no_pods_reports_not_ready():
    svc, _ = _svc_with_pods([])
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result == {"ready": False, "waiting_reason": None, "waiting_message": None}


def test_api_error_reports_not_ready():
    svc, core = _svc_with_pods([])
    core.list_namespaced_pod.side_effect = ApiException(status=500)
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result == {"ready": False, "waiting_reason": None, "waiting_message": None}


def test_ready_true_if_any_pod_ready():
    # A later not-ready pod must not overwrite an earlier ready=True.
    svc, _ = _svc_with_pods([_pod(ready=True), _pod(ready=False)])
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result["ready"] is True


def test_first_waiting_container_across_pods_wins():
    # First waiting container found (pod order, then container order) wins.
    svc, _ = _svc_with_pods(
        [
            _pod(ready=False, waiting_reason="ImagePullBackOff", waiting_message="pull failed"),
            _pod(ready=False, waiting_reason="CrashLoopBackOff", waiting_message="back-off"),
        ]
    )
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result["waiting_reason"] == "ImagePullBackOff"
    assert result["waiting_message"] == "pull failed"


def test_waiting_reason_picked_up_from_later_pod_when_first_has_none():
    # A ready pod with no waiting container, plus a crash-looping pod → surface the crash.
    svc, _ = _svc_with_pods(
        [
            _pod(ready=True),
            _pod(ready=False, waiting_reason="CrashLoopBackOff", waiting_message="back-off"),
        ]
    )
    result = svc.get_workload_pod_status("team1", "app.kubernetes.io/name=petstore")
    assert result["ready"] is True
    assert result["waiting_reason"] == "CrashLoopBackOff"
