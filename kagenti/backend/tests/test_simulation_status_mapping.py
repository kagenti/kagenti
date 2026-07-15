# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Tests for the generation-status mapping (issue #2162)."""

from app.routers.simulation import map_generation_status


def _map(harness=None, ready=False, reason=None, message=None, elapsed=1.0, timeout=600):
    # `ready` is accepted for call-site compatibility; the mapper does not
    # depend on pod readiness (reachability + waiting reason drive the result).
    return map_generation_status(
        harness=harness,
        pod_waiting_reason=reason,
        pod_waiting_message=message,
        elapsed_seconds=elapsed,
        timeout_seconds=timeout,
    )


def test_harness_pending_maps_to_generating():
    assert _map(harness={"status": "pending"}).status == "Generating"


def test_harness_initializing_maps_to_generating():
    assert _map(harness={"status": "initializing"}).status == "Generating"


def test_harness_ready_maps_to_ready_with_mcp_url():
    out = _map(harness={"status": "ready", "mcp_url": "http://x/mcp/petstore"})
    assert out.status == "Ready"
    assert out.mcpUrl == "http://x/mcp/petstore"


def test_harness_failed_surfaces_error_code_and_message():
    out = _map(
        harness={
            "status": "failed",
            "error": {"code": "skill_generation_failed", "message": "LLM error"},
        }
    )
    assert out.status == "Failed"
    assert out.reason == "skill_generation_failed: LLM error"


def test_crashloop_pod_maps_to_error_when_harness_unreachable():
    out = _map(harness=None, ready=False, reason="CrashLoopBackOff", message="back-off")
    assert out.status == "Error"
    assert out.reason == "CrashLoopBackOff: back-off"


def test_missing_secret_config_error_maps_to_error():
    out = _map(harness=None, reason="CreateContainerConfigError", message="secret not found")
    assert out.status == "Error"
    assert out.reason == "CreateContainerConfigError: secret not found"


def test_healthy_pod_no_harness_within_timeout_is_generating():
    out = _map(harness=None, ready=True, elapsed=30.0, timeout=600)
    assert out.status == "Generating"


def test_no_harness_past_timeout_maps_to_failed_stalled():
    out = _map(harness=None, ready=True, elapsed=700.0, timeout=600)
    assert out.status == "Failed"
    assert out.reason == "generation_stalled"


def test_failed_missing_code_defaults_to_unknown():
    out = _map(harness={"status": "failed", "error": {"message": "boom"}})
    assert out.status == "Failed"
    assert out.reason == "unknown: boom"


def test_failed_empty_message_uses_code_only():
    out = _map(harness={"status": "failed", "error": {"code": "creation_timeout", "message": ""}})
    assert out.status == "Failed"
    assert out.reason == "creation_timeout"


def test_failed_message_with_trailing_colon_is_preserved():
    out = _map(
        harness={"status": "failed", "error": {"code": "sidecar_start_failed", "message": "died: "}}
    )
    assert out.status == "Failed"
    assert out.reason == "sidecar_start_failed: died: "


def test_failed_folds_cause_type_into_reason():
    # The harness records the underlying cause (e.g. a timed-out generation
    # stage rewrapped as a generic RuntimeError) in error.details.cause_type.
    # It must surface in the reason so the UI shows *why* it failed.
    out = _map(
        harness={
            "status": "failed",
            "error": {
                "code": "skill_generation_failed",
                "message": "Skill generation failed for 'tasks'",
                "details": {"cause_type": "TimeoutError", "cause": ""},
            },
        }
    )
    assert out.status == "Failed"
    assert (
        out.reason == "skill_generation_failed (TimeoutError): Skill generation failed for 'tasks'"
    )


def test_failed_cause_type_with_empty_message_uses_code_and_cause():
    out = _map(
        harness={
            "status": "failed",
            "error": {
                "code": "skill_generation_failed",
                "message": "",
                "details": {"cause_type": "TimeoutError"},
            },
        }
    )
    assert out.status == "Failed"
    assert out.reason == "skill_generation_failed (TimeoutError)"


def test_failed_details_without_cause_type_unchanged():
    out = _map(
        harness={
            "status": "failed",
            "error": {
                "code": "instance_init_failed",
                "message": "boom",
                "details": {"exception": "RuntimeError"},
            },
        }
    )
    assert out.status == "Failed"
    assert out.reason == "instance_init_failed: boom"
