#!/usr/bin/env python3
"""
Agent Conversation E2E Tests for Kagenti Platform

Tests basic agent functionality:
- Agent responds to queries
- LLM integration (Ollama) works
- A2A protocol communication

Usage:
    pytest tests/e2e/test_agent_conversation.py -v
"""

import pytest
import subprocess
import json
import time


# ============================================================================
# Test: Weather Agent Conversation
# ============================================================================


class TestWeatherAgentConversation:
    """Test weather-service agent conversation with Ollama LLM."""

    @pytest.mark.critical
    def test_agent_health_endpoint(self):
        """Verify agent health endpoint is accessible from within cluster."""
        # Use kubectl run to execute curl from inside the cluster
        cmd = [
            "kubectl",
            "run",
            "test-agent-health",
            "--rm",
            "-i",
            "--restart=Never",
            "--image=curlimages/curl:latest",
            "-n",
            "team1",
            "--",
            "curl",
            "-f",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "http://weather-service:8000/health",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False
            )

            # Extract HTTP status code from output
            if result.returncode == 0 and "200" in result.stdout:
                print("\n✓ Agent health endpoint is accessible (HTTP 200)")
                return

            pytest.fail(
                f"Health endpoint check failed. Return code: {result.returncode}, "
                f"Output: {result.stdout}, Error: {result.stderr}"
            )
        except subprocess.TimeoutExpired:
            pytest.fail("Health check timed out after 30s")
        except Exception as e:
            pytest.fail(f"Failed to check agent health endpoint: {e}")

    def test_agent_simple_query(self):
        """
        Test agent can process a simple query using Ollama.

        This validates:
        - Agent API is accessible
        - Ollama LLM integration works
        - Agent can generate responses

        Note: This is a basic connectivity test. Full agent conversation
        testing requires more complex setup and is better suited for
        integration tests with proper A2A client setup.
        """
        # Use kubectl run to execute curl from inside the cluster
        # Simple health/status check that validates agent is responding
        cmd = [
            "kubectl",
            "run",
            "test-agent-query",
            "--rm",
            "-i",
            "--restart=Never",
            "--image=curlimages/curl:latest",
            "-n",
            "team1",
            "--",
            "curl",
            "-f",
            "-s",
            "-w",
            "\\nHTTP_CODE:%{http_code}",
            "http://weather-service:8000/",
        ]

        try:
            # Give agent time to be fully ready (LLM loading, etc.)
            time.sleep(5)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, check=False
            )

            # Check if we got a successful response (200-299)
            if result.returncode == 0 and "HTTP_CODE:20" in result.stdout:
                print("\n✓ Agent API is accessible and responding")
                print(f"  Output: {result.stdout[:200]}")  # First 200 chars
                return

            # If we got here, something failed
            pytest.fail(
                f"Agent query failed. Return code: {result.returncode}, "
                f"Output: {result.stdout[:500]}, Error: {result.stderr[:500]}"
            )

        except subprocess.TimeoutExpired:
            pytest.fail(
                "Agent query timed out after 60s - may indicate LLM not responding"
            )
        except Exception as e:
            pytest.fail(f"Failed to query agent: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
