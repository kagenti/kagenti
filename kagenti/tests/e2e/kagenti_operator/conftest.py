"""
Kagenti Operator-specific test fixtures.

Provides correct service names and resource expectations for kagenti-operator mode.
"""

import pytest


@pytest.fixture(scope="session")
def weather_service_name():
    """
    Weather agent service name in kagenti-operator mode.

    Kagenti operator creates service with same name as the agent.
    """
    return "weather-service"


@pytest.fixture(scope="session")
def weather_tool_service_name():
    """
    Weather tool service name in kagenti-operator mode.

    Tools use standard Kubernetes Deployments + Services with {name}-mcp naming.
    """
    return "weather-tool-mcp"
