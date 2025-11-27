"""
Platform Operator-specific test fixtures.

Provides correct service names and resource expectations for platform-operator mode.
"""

import pytest


@pytest.fixture(scope="session")
def weather_service_name():
    """
    Weather agent service name in platform-operator mode.

    Platform operator creates service without suffix.
    """
    return "weather-service"


@pytest.fixture(scope="session")
def weather_tool_service_name():
    """
    Weather tool service name in platform-operator mode.

    Platform operator creates service without prefix/suffix.
    """
    return "weather-tool"
