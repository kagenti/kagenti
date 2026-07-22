# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for KubernetesService.list_statefulset_pvcs (issue #2163, generic PVC discovery)."""

from unittest.mock import MagicMock

from kubernetes.client import ApiException

from app.services.kubernetes import KubernetesService


def _svc(sts=None, sts_exc=None, pvcs=None):
    """A KubernetesService with get_statefulset / list_persistent_volume_claims stubbed."""
    svc = object.__new__(KubernetesService)  # skip __init__ (no kube config load)
    if sts_exc is not None:
        svc.get_statefulset = MagicMock(side_effect=sts_exc)
    else:
        svc.get_statefulset = MagicMock(return_value=sts)
    svc.list_persistent_volume_claims = MagicMock(return_value=pvcs or [])
    return svc


def _sts_dict(template_names=("data",)):
    return {"spec": {"volume_claim_templates": [{"metadata": {"name": t}} for t in template_names]}}


def test_matches_template_ordinal_pvcs():
    svc = _svc(
        sts=_sts_dict(("data",)),
        pvcs=["data-petstore-0", "data-other-0", "unrelated"],
    )
    assert svc.list_statefulset_pvcs("team1", "petstore") == ["data-petstore-0"]


def test_catches_scaled_down_ordinals():
    # replicas may now be 1, but ordinal-1 PVC lingers (StatefulSet never auto-deletes).
    svc = _svc(sts=_sts_dict(("data",)), pvcs=["data-petstore-0", "data-petstore-1"])
    assert sorted(svc.list_statefulset_pvcs("team1", "petstore")) == [
        "data-petstore-0",
        "data-petstore-1",
    ]


def test_multiple_templates():
    svc = _svc(
        sts=_sts_dict(("data", "cache")),
        pvcs=["data-petstore-0", "cache-petstore-0", "data-petstore-x"],
    )
    assert sorted(svc.list_statefulset_pvcs("team1", "petstore")) == [
        "cache-petstore-0",
        "data-petstore-0",
    ]


def test_no_statefulset_returns_empty():
    svc = _svc(sts_exc=ApiException(status=404))
    assert svc.list_statefulset_pvcs("team1", "petstore") == []


def test_no_templates_returns_empty():
    svc = _svc(sts={"spec": {}}, pvcs=["data-petstore-0"])
    assert svc.list_statefulset_pvcs("team1", "petstore") == []


def test_non_404_error_propagates():
    import pytest

    svc = _svc(sts_exc=ApiException(status=403))
    with pytest.raises(ApiException):
        svc.list_statefulset_pvcs("team1", "petstore")
