#!/usr/bin/env python3
"""
Agent Conversation E2E Tests for Kagenti Platform

Tests agent conversation functionality via A2A protocol:
- Agent responds to queries via A2A protocol
- LLM integration (Ollama) works
- Agent can process weather queries

Usage:
    pytest tests/e2e/test_agent_conversation.py -v
"""

import asyncio
import os
import pathlib
import logging

import pytest
import httpx
import yaml
from uuid import uuid4
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    Message as A2AMessage,
    TextPart,
    TaskArtifactUpdateEvent,
    TaskState,
)

# LLM responses can be flaky (empty/null content from the model).
# Retry the query up to this many times before failing.
# TODO: Replace with sandbox agent tests that have built-in tool call
# retry and exponential backoff at the agent/platform level (sandbox.py
# SSE reconnection, looper sidecar auto-continue). The basic weather
# agent has no resilience — it fails immediately on external API errors.
_LLM_QUERY_MAX_ATTEMPTS = 5
_LLM_QUERY_RETRY_DELAY_S = 10

# Import CA certificate fetching from conftest
from kagenti.tests.e2e.conftest import (
    _fetch_openshift_ingress_ca,
)

logger = logging.getLogger(__name__)


def _is_openshift_from_config():
    """Detect if running on OpenShift from KAGENTI_CONFIG_FILE."""
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return False

    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
        config_path = repo_root / config_file

    if not config_path.exists():
        return False

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return False

    # Check various locations for openshift flag
    if config.get("openshift", False):
        return True

    charts = config.get("charts", {})
    if charts.get("kagenti-deps", {}).get("values", {}).get("openshift", False):
        return True
    if charts.get("kagenti", {}).get("values", {}).get("openshift", False):
        return True

    return False


def _get_ssl_context():
    """
    Get the SSL context for httpx client.

    On OpenShift: Returns ssl.SSLContext with the cluster CA certificate.
    On Kind: Returns True (default SSL verification, services use HTTP).

    Never returns False - raises if CA cert cannot be fetched on OpenShift.
    """
    import ssl

    if not _is_openshift_from_config():
        return True

    # Check environment variable first (allows override)
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if not ca_path or not pathlib.Path(ca_path).exists():
        # Fetch from cluster
        ca_path = _fetch_openshift_ingress_ca()

    if not ca_path:
        raise RuntimeError(
            "Could not fetch OpenShift ingress CA certificate. "
            "Set OPENSHIFT_INGRESS_CA env var to the CA bundle path."
        )

    return ssl.create_default_context(cafile=ca_path)


# ============================================================================
# Test: Weather Agent Conversation via A2A Protocol (Both Operators)
# ============================================================================


# Truncation limits for diagnostic output in assertion messages
_DIAG_TEXT_LIMIT = 200
_DIAG_ARTIFACT_LIMIT = 100
_DIAG_ERROR_LIMIT = 500


def _extract_text_from_parts(parts):
    """Extract concatenated text from a list of A2A Part objects."""
    return "".join(
        p.text
        for part in (parts or [])
        for p in [getattr(part, "root", part)]
        if hasattr(p, "text")
    )


def _task_diagnostic(task):
    """Build a diagnostic string from an A2A Task for assertion messages."""
    if not task:
        return "task=None"
    lines = []
    status = getattr(task, "status", None)
    if status:
        lines.append(f"task.status.state={getattr(status, 'state', '?')}")
        msg = getattr(status, "message", None)
        if msg:
            text = _extract_text_from_parts(getattr(msg, "parts", []))
            if text:
                lines.append(f"task.status.message={text[:_DIAG_TEXT_LIMIT]}")
    artifacts = getattr(task, "artifacts", None)
    lines.append(f"task.artifacts count={len(artifacts) if artifacts else 0}")
    if artifacts:
        for i, art in enumerate(artifacts):
            art_text = _extract_text_from_parts(getattr(art, "parts", []))
            lines.append(f"  artifact[{i}] text={art_text[:_DIAG_ARTIFACT_LIMIT]!r}")
    return "\n    ".join(lines)


async def _send_and_collect_response(client, user_message, context_id=None):
    """Send a message to the agent and collect the response.

    Returns a dict with keys: full_response, events_received, last_task, task_failed.
    """
    message = A2AMessage(
        role="user",
        parts=[TextPart(text=user_message)],
        messageId=uuid4().hex,
        **({"contextId": context_id} if context_id else {}),
    )

    full_response = ""
    events_received = []
    last_task = None
    task_failed = False

    async for result in client.send_message(message):
        logger.debug("Received result type: %s", type(result))
        if isinstance(result, tuple):
            task, event = result
            last_task = task
            event_name = type(event).__name__ if event else "Task(final)"
            events_received.append(event_name)
            logger.debug("Event: %s", event_name)
            logger.debug("Task: %s", _task_diagnostic(task))
            if event:
                logger.debug("Event details: %s", event)

            # Check for failed task
            status = getattr(task, "status", None)
            if status and getattr(status, "state", None) == TaskState.failed:
                task_failed = True
                status_msg = getattr(status, "message", None)
                if status_msg:
                    full_response += _extract_text_from_parts(
                        getattr(status_msg, "parts", [])
                    )

            # Extract from TaskArtifactUpdateEvent
            if isinstance(event, TaskArtifactUpdateEvent):
                if hasattr(event, "artifact") and event.artifact:
                    extracted = _extract_text_from_parts(event.artifact.parts)
                    logger.debug(
                        "Extracted from TaskArtifactUpdateEvent: %s",
                        extracted[:200] if extracted else "",
                    )
                    full_response += extracted

            # Extract from final task (event=None means complete)
            if event is None and task and task.artifacts:
                logger.debug("Final task has %d artifacts", len(task.artifacts))
                for i, artifact in enumerate(task.artifacts):
                    extracted = _extract_text_from_parts(artifact.parts)
                    logger.debug(
                        "Extracted from artifact[%d]: %s",
                        i,
                        extracted[:200] if extracted else "",
                    )
                    full_response += extracted

        elif isinstance(result, A2AMessage):
            events_received.append("Message")
            extracted = _extract_text_from_parts(result.parts)
            logger.debug(
                "Extracted from A2AMessage: %s",
                extracted[:200] if extracted else "",
            )
            logger.debug("Message parts: %s", result.parts)
            full_response += extracted

    return {
        "full_response": full_response,
        "events_received": events_received,
        "last_task": last_task,
        "task_failed": task_failed,
    }


class TestWeatherAgentConversation:
    """Test weather-service agent with MCP weather-tool (works with both operators).

    These tests depend on the external Open-Meteo API (api.open-meteo.com).
    They may fail in CI due to network restrictions, rate limiting, or API
    outages — the basic weather agent has no built-in tool call retry.

    TODO: Replace these tests with sandbox agent tests once the sandbox
    backend is merged. The sandbox agent has built-in resilience:
    - SSE reconnection with exponential backoff (sandbox.py)
    - Looper sidecar for auto-continue on transient failures
    - Tool call errors are retried at the agent framework level
    """

    @pytest.mark.asyncio
    async def test_agent_simple_query(self, keycloak_agent_token):
        """
        Test agent can process a simple query using A2A protocol.

        This validates:
        - A2A protocol client works (ClientFactory API)
        - Agent API is accessible via A2A
        - LLM integration works (Ollama on Kind, OpenAI on OpenShift)
        - Agent can generate responses to weather queries
        """
        agent_url = os.getenv("AGENT_URL", "http://localhost:8000")
        ssl_verify = _get_ssl_context()

        # On OpenShift, traffic goes through AuthBridge (envoy sidecar) which
        # requires a valid Bearer token from the kagenti Keycloak realm.
        headers = {}
        if keycloak_agent_token:
            headers["Authorization"] = f"Bearer {keycloak_agent_token}"

        # Connect using ClientFactory (replaces deprecated A2AClient)
        # TODO: Should the agent card return the public route URL instead of
        #   the internal bind address (0.0.0.0:8000)? The A2A spec says the
        #   card URL should be the agent's reachable endpoint. Options:
        #   1. Agent reads its own route hostname and sets card.url
        #   2. A proxy/gateway rewrites the card URL on the fly
        #   3. Clients override as we do here (current workaround)
        httpx_client = httpx.AsyncClient(
            timeout=120.0, verify=ssl_verify, headers=headers
        )
        config = ClientConfig(httpx_client=httpx_client)
        try:
            from a2a.client.card_resolver import A2ACardResolver

            resolver = A2ACardResolver(httpx_client, agent_url)
            card = await resolver.get_agent_card()
            # Override: card.url is the pod's internal address (0.0.0.0:8000)
            # but we connect via the external route
            card.url = agent_url
            client = await ClientFactory.connect(card, client_config=config)
        except Exception as e:
            pytest.fail(
                f"Agent not reachable at {agent_url}: {e}\n"
                "Check: pod running, port-forward active, service exists"
            )

        user_message = "What is the weather like in San Francisco?"

        # Retry on empty response — LLM can return empty/null content intermittently
        last_result = None
        for attempt in range(1, _LLM_QUERY_MAX_ATTEMPTS + 1):
            try:
                last_result = await _send_and_collect_response(client, user_message)
            except Exception as e:
                pytest.fail(f"Error during A2A conversation: {e}")

            if last_result["task_failed"]:
                error_text = last_result["full_response"][:_DIAG_ERROR_LIMIT]
                # Retry on transient failures — the weather-tool pod may still
                # be initializing, or the LLM/tool may return transient errors.
                _TRANSIENT_ERRORS = (
                    "Cannot connect",
                    "Expecting value",
                    "Error calling tool",
                    "timed out",
                    "Read timed out",
                    "ConnectionPool",
                )
                is_transient = any(err in error_text for err in _TRANSIENT_ERRORS)
                if is_transient and attempt < _LLM_QUERY_MAX_ATTEMPTS:
                    logger.warning(
                        "Transient error on attempt %d/%d, retrying in %ds...\n  %s",
                        attempt,
                        _LLM_QUERY_MAX_ATTEMPTS,
                        _LLM_QUERY_RETRY_DELAY_S,
                        error_text[:200],
                    )
                    await asyncio.sleep(_LLM_QUERY_RETRY_DELAY_S)
                    continue
                if is_transient:
                    # All retries exhausted on a transient error (external API
                    # unreachable). Skip instead of fail — this is not an agent
                    # or platform bug, just network/API unavailability in CI.
                    pytest.skip(
                        f"External API unreachable after {_LLM_QUERY_MAX_ATTEMPTS} attempts: "
                        f"{error_text[:120]}"
                    )
                pytest.fail(
                    f"Agent returned a FAILED task\n"
                    f"  Agent URL: {agent_url}\n"
                    f"  Query: {user_message}\n"
                    f"  Error: {error_text}\n"
                    f"  Task details:\n    {_task_diagnostic(last_result['last_task'])}"
                )

            if last_result["full_response"]:
                if attempt > 1:
                    logger.info(
                        "Got response on attempt %d/%d",
                        attempt,
                        _LLM_QUERY_MAX_ATTEMPTS,
                    )
                break

            logger.warning(
                "Empty response on attempt %d/%d, retrying in %ds...",
                attempt,
                _LLM_QUERY_MAX_ATTEMPTS,
                _LLM_QUERY_RETRY_DELAY_S,
            )
            if attempt < _LLM_QUERY_MAX_ATTEMPTS:
                await asyncio.sleep(_LLM_QUERY_RETRY_DELAY_S)

        full_response = last_result["full_response"]
        events_received = last_result["events_received"]
        last_task = last_result["last_task"]

        # Validate response
        assert full_response, (
            f"Agent did not return any response after {_LLM_QUERY_MAX_ATTEMPTS} attempts\n"
            f"  Agent URL: {agent_url}\n"
            f"  Events received: {events_received}\n"
            f"  Query: {user_message}\n"
            f"  Task details:\n    {_task_diagnostic(last_task)}"
        )
        assert len(full_response) > 10, f"Agent response too short: {full_response}"

        logger.debug(
            "Agent responded via A2A (ClientFactory); events=%s; response=%s...",
            events_received,
            full_response[:200],
        )

        # Weather-related keywords that should appear if tool was called successfully
        # The tool returns actual weather data (temperature, conditions, location)
        weather_data_keywords = [
            "weather",
            "temperature",
            "san francisco",
            "°",
            "degrees",
            "sunny",
            "cloudy",
            "rain",
            "forecast",
            "current",
            "conditions",
        ]

        response_lower = full_response.lower()
        has_weather_data = any(
            keyword in response_lower for keyword in weather_data_keywords
        )

        assert has_weather_data, (
            f"Agent response doesn't contain weather data from tool. "
            f"Response: {full_response}"
        )

        logger.debug(
            "Agent responded via A2A; weather MCP invoked; query=%s; response=%s...",
            user_message,
            full_response[:200],
        )

    @pytest.mark.openshift_only
    @pytest.mark.asyncio
    async def test_agent_multiturn_conversation(
        self, test_session_id, keycloak_agent_token
    ):
        """
        Test multi-turn conversation maintains consistent session/context ID.

        This validates:
        - Multiple messages can share the same contextId
        - Session tracking works across conversation turns
        - Observability traces can be grouped by session

        The test_session_id fixture provides a unique ID for this test run,
        allowing observability tests to filter traces by this specific session.
        """
        agent_url = os.getenv("AGENT_URL", "http://localhost:8000")
        ssl_verify = _get_ssl_context()

        # AuthBridge Bearer token (see test_agent_simple_query for details)
        headers = {}
        if keycloak_agent_token:
            headers["Authorization"] = f"Bearer {keycloak_agent_token}"

        context_id = test_session_id
        logger.debug("Multi-turn conversation test; session/context ID: %s", context_id)

        messages = [
            "What is the weather in Paris?",
            "And what about London?",
            "Which city is warmer?",
        ]

        # Connect using ClientFactory (override card URL for external access)
        httpx_client = httpx.AsyncClient(
            timeout=120.0, verify=ssl_verify, headers=headers
        )
        config = ClientConfig(httpx_client=httpx_client)
        try:
            from a2a.client.card_resolver import A2ACardResolver

            resolver = A2ACardResolver(httpx_client, agent_url)
            card = await resolver.get_agent_card()
            card.url = agent_url
            client = await ClientFactory.connect(card, client_config=config)
        except Exception as e:
            pytest.fail(f"Agent not reachable at {agent_url}: {e}")

        for turn, user_message in enumerate(messages, 1):
            logger.debug("Turn %d: %s", turn, user_message)

            # Retry on empty response — LLM can return empty content intermittently
            last_result = None
            for attempt in range(1, _LLM_QUERY_MAX_ATTEMPTS + 1):
                try:
                    last_result = await _send_and_collect_response(
                        client, user_message, context_id=context_id
                    )
                except Exception as e:
                    pytest.fail(f"Turn {turn} failed: {e}")

                if last_result["task_failed"]:
                    error_text = last_result["full_response"][:_DIAG_ERROR_LIMIT]
                    _TRANSIENT = (
                        "Cannot connect",
                        "Expecting value",
                        "Error calling tool",
                        "timed out",
                        "ConnectionPool",
                    )
                    is_transient = any(err in error_text for err in _TRANSIENT)
                    if is_transient and attempt < _LLM_QUERY_MAX_ATTEMPTS:
                        logger.warning(
                            "Turn %d: transient error on attempt %d/%d, retrying...",
                            turn,
                            attempt,
                            _LLM_QUERY_MAX_ATTEMPTS,
                        )
                        await asyncio.sleep(_LLM_QUERY_RETRY_DELAY_S)
                        continue
                    if is_transient:
                        pytest.skip(
                            f"Turn {turn}: external API unreachable after "
                            f"{_LLM_QUERY_MAX_ATTEMPTS} attempts: {error_text[:120]}"
                        )
                    pytest.fail(
                        f"Turn {turn}: Agent returned FAILED task\n"
                        f"  Error: {error_text}\n"
                        f"  Task details:\n"
                        f"    {_task_diagnostic(last_result['last_task'])}"
                    )

                if last_result["full_response"]:
                    if attempt > 1:
                        logger.info(
                            "Turn %d: got response on attempt %d/%d",
                            turn,
                            attempt,
                            _LLM_QUERY_MAX_ATTEMPTS,
                        )
                    break

                logger.warning(
                    "Turn %d: empty response on attempt %d/%d, retrying in %ds...",
                    turn,
                    attempt,
                    _LLM_QUERY_MAX_ATTEMPTS,
                    _LLM_QUERY_RETRY_DELAY_S,
                )
                if attempt < _LLM_QUERY_MAX_ATTEMPTS:
                    await asyncio.sleep(_LLM_QUERY_RETRY_DELAY_S)

            assert last_result["full_response"], (
                f"Turn {turn}: Agent did not return any response"
                f" after {_LLM_QUERY_MAX_ATTEMPTS} attempts\n"
                f"  Events received: {last_result['events_received']}\n"
                f"  Task details:\n    {_task_diagnostic(last_result['last_task'])}"
            )
            logger.debug(
                "Turn %d response: %s...", turn, last_result["full_response"][:100]
            )

        logger.debug(
            "Multi-turn conversation completed (%d turns); context ID: %s",
            len(messages),
            context_id,
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
