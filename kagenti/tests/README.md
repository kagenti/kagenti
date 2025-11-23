# Kagenti E2E Tests

End-to-end tests for Kagenti platform deployment validation.

## Test Structure

```
tests/
├── README.md              # This file
├── requirements.txt       # Test dependencies
├── conftest.py           # Shared pytest fixtures
└── e2e/                  # E2E test suite
    ├── __init__.py
    ├── conftest.py       # E2E-specific fixtures
    ├── test_deployment_health.py
    ├── test_keycloak.py
    └── test_weather_agents.py
```

## Running Tests

### Prerequisites

1. **Deploy Kagenti platform** to a Kubernetes cluster (Kind, OpenShift, etc.)
2. **Install test dependencies**:
   ```bash
   cd kagenti/tests
   pip install -r requirements.txt
   ```

### Run All E2E Tests

```bash
# From kagenti/ directory
pytest tests/e2e/ -v
```

### Run Specific Test File

```bash
pytest tests/e2e/test_deployment_health.py -v
```

### Run Specific Test

```bash
pytest tests/e2e/test_deployment_health.py::TestDeploymentHealth::test_weather_tool_healthy -v
```

### Run with Timeout

```bash
pytest tests/e2e/ -v --timeout=300
```

### Run in Parallel

```bash
pytest tests/e2e/ -v -n auto
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

- `k8s_client` - Kubernetes CoreV1Api client
- `k8s_apps_client` - Kubernetes AppsV1Api client
- `keycloak_admin_credentials` - Keycloak admin username/password
- `keycloak_token` - Keycloak access token (session-scoped)
- `excluded_apps` - Set of excluded app names

## Troubleshooting

### Tests Fail with "Connection refused"

Ensure kubectl is configured:
```bash
kubectl cluster-info
```

### Tests Fail with "Timeout waiting for..."

Increase timeout:
```bash
pytest tests/e2e/ -v --app-timeout=600
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

- ✅ Deployment health checks
- ✅ Keycloak authentication
- ✅ Weather agents deployment
- ⏳ Weather tool functionality (pending LLM mocking)
- ⏳ Agent-to-tool integration (pending LLM mocking)
- ⏳ SPIRE workload identity (optional)
- ⏳ Istio mTLS (optional)
- ⏳ Phoenix observability (optional)
