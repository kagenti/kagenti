# Kagenti E2E Tests

End-to-end tests for Kagenti platform deployment validation.

## Test Structure

```
tests/
├── README.md                      # This file
├── conftest.py                    # Shared pytest fixtures
└── e2e/                           # E2E test suite
    ├── __init__.py
    ├── conftest.py                # E2E-specific fixtures
    ├── test_deployment_health.py  # Platform, deployments, services health
    └── test_agent_conversation.py # Agent A2A conversation with Ollama
```

**Note**: Test dependencies are now defined in the root `pyproject.toml` under `[project.optional-dependencies.test]`.

## Running Tests

### Prerequisites

1. **Deploy Kagenti platform** to a Kubernetes cluster (Kind, OpenShift, etc.)
2. **Install test dependencies**:
   ```bash
   # From repository root
   pip install -e .[test]
   ```
3. **For agent conversation tests**, set up port-forwarding if testing from outside the cluster:
   ```bash
   kubectl port-forward -n team1 svc/weather-service 8000:8000
   ```

### Run All E2E Tests

```bash
# From kagenti/ directory
pytest tests/e2e/ -v

# Or with AGENT_URL for agent conversation tests
AGENT_URL=http://localhost:8000 pytest tests/e2e/ -v
```

### Run Specific Test File

```bash
# Deployment health tests
pytest tests/e2e/test_deployment_health.py -v

# Agent conversation tests (requires port-forward or in-cluster access)
AGENT_URL=http://localhost:8000 pytest tests/e2e/test_agent_conversation.py -v
```

### Run Specific Test

```bash
pytest tests/e2e/test_deployment_health.py::TestPlatformHealth::test_no_failed_pods -v
pytest tests/e2e/test_agent_conversation.py::TestWeatherAgentConversation::test_agent_simple_query -v
```

### Run with Timeout

```bash
pytest tests/e2e/ -v --timeout=300
```

### Run in Parallel

```bash
pytest tests/e2e/ -v -n auto
```

## Environment Variables

### Test Configuration

- `AGENT_URL` - Agent service URL for conversation tests
  - **Default**: `http://localhost:8000`
  - **In-cluster**: `http://weather-service.team1.svc.cluster.local:8000`
  - **Port-forwarded**: `http://localhost:8000`

  Example:
  ```bash
  # From outside cluster (requires port-forward)
  kubectl port-forward -n team1 svc/weather-service 8000:8000 &
  AGENT_URL=http://localhost:8000 pytest tests/e2e/test_agent_conversation.py -v

  # From inside cluster (CI environment)
  AGENT_URL=http://weather-service.team1.svc.cluster.local:8000 pytest tests/e2e/ -v
  ```

## Test Options

### Custom Options

- `--exclude-app <apps>` - Comma-separated list of apps to exclude from tests
  ```bash
  pytest tests/e2e/ -v --exclude-app=spire,istio
  ```

- `--app-timeout <seconds>` - Timeout for waiting for applications (default: 300)
  ```bash
  pytest tests/e2e/ -v --app-timeout=600
  ```

- `--only-critical` - Only run critical tests
  ```bash
  pytest tests/e2e/ -v --only-critical
  ```

### Pytest Built-in Options

- `-v` - Verbose output
- `-s` - Show print statements
- `-x` - Stop on first failure
- `-k <pattern>` - Run tests matching pattern
  ```bash
  pytest tests/e2e/ -v -k "weather"
  ```
- `-m <marker>` - Run tests with specific marker
  ```bash
  pytest tests/e2e/ -v -m critical
  ```

## Test Markers

Tests use pytest markers to categorize:

- `@pytest.mark.critical` - Critical tests that must pass
- `@pytest.mark.slow` - Slow tests (>10 seconds)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.auth` - Authentication/authorization tests

Run only critical tests:
```bash
pytest tests/e2e/ -v -m critical
```

Skip slow tests:
```bash
pytest tests/e2e/ -v -m "not slow"
```

## CI Integration

Tests are automatically run in GitHub Actions PR workflow:

See `.github/workflows/pr-kind-deployment.yaml`

## Writing New Tests

### Test Structure

```python
import pytest
from kubernetes import client, config

class TestMyFeature:
    """Test my feature description."""

    @pytest.mark.critical
    def test_basic_functionality(self, k8s_client):
        """Test basic functionality."""
        # Arrange
        namespace = "team1"

        # Act
        pods = k8s_client.list_namespaced_pod(namespace)

        # Assert
        assert len(pods.items) > 0, "Expected pods in team1 namespace"
```

### Using Fixtures

Common fixtures available (see `conftest.py`):

- `k8s_client` - Kubernetes CoreV1Api client (session-scoped)
- `k8s_apps_client` - Kubernetes AppsV1Api client (session-scoped)
- `excluded_apps` - Set of excluded app names from `--exclude-app` option (session-scoped)
- `app_timeout` - Timeout in seconds from `--app-timeout` option (session-scoped, default: 300)
- `keycloak_admin_credentials` - Keycloak admin username/password from K8s secret (session-scoped)
- `keycloak_token` - Keycloak JWT access token acquired via admin credentials (session-scoped)

## Troubleshooting

### Tests Fail with "Connection refused"

**For deployment health tests:**
Ensure kubectl is configured:
```bash
kubectl cluster-info
```

**For agent conversation tests:**
Set up port-forwarding to the agent service:
```bash
kubectl port-forward -n team1 svc/weather-service 8000:8000 &
AGENT_URL=http://localhost:8000 pytest tests/e2e/test_agent_conversation.py -v
```

### Tests Fail with "Timeout waiting for..."

Increase timeout:
```bash
pytest tests/e2e/ -v --app-timeout=600
```

### Agent Conversation Test Fails

**DNS Resolution Errors:**
```bash
# Test is trying to reach cluster DNS from outside
# Solution: Use port-forward or set AGENT_URL
kubectl port-forward -n team1 svc/weather-service 8000:8000 &
AGENT_URL=http://localhost:8000 pytest tests/e2e/test_agent_conversation.py -v
```

**Agent Not Responding:**
```bash
# Check agent pod status
kubectl get pods -n team1 -l app=weather-service
kubectl logs -n team1 deployment/weather-service --tail=100

# Check if Ollama is running
kubectl get pods -n ollama-system
kubectl logs -n ollama-system deployment/ollama --tail=50
```

**Tool Invocation Not Detected:**
```bash
# Check weather-tool is running
kubectl get pods -n team1 -l app=weather-tool
kubectl logs -n team1 deployment/weather-tool --tail=100

# Verify MCP server configuration in agent
kubectl describe deployment -n team1 weather-service
```

### Keycloak Authentication Fails

Check Keycloak is accessible:
```bash
kubectl get deployment keycloak -n keycloak
kubectl get service keycloak -n keycloak
```

Port-forward if needed:
```bash
kubectl port-forward -n keycloak service/keycloak 8080:8080
```

### Skip Failing Components

Exclude problematic apps:
```bash
pytest tests/e2e/ -v --exclude-app=spire,istio,phoenix
```

## Test Coverage

Current test coverage:

### ✅ Implemented Tests

- **Platform Health** (`test_deployment_health.py`)
  - No failed pods in cluster
  - No crashlooping pods (>3 restarts)

- **Weather Tool Deployment** (`test_deployment_health.py`)
  - Deployment exists and ready
  - Pods running without issues
  - Service exists with endpoints

- **Weather Service (Agent) Deployment** (`test_deployment_health.py`)
  - Deployment exists and ready
  - Pods running without issues
  - Service exists with endpoints

- **Keycloak Deployment** (`test_deployment_health.py`)
  - Namespace exists
  - Deployment/StatefulSet ready (skippable)

- **Platform Operator** (`test_deployment_health.py`)
  - Controller manager deployment ready (skippable)

- **Agent Conversation** (`test_agent_conversation.py`)
  - ✅ A2A protocol client communication
  - ✅ Ollama LLM integration
  - ✅ Weather MCP tool invocation
  - ✅ Agent can process weather queries
  - ✅ Tool responses contain weather data

### ⏳ Future Test Coverage

- SPIRE workload identity validation (optional)
- Istio mTLS certificate verification (optional)
- Phoenix observability traces (optional)
- Multi-agent orchestration scenarios
