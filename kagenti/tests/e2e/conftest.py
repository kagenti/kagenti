"""
E2E-specific pytest fixtures.

Config-driven fixtures that adapt tests based on installer configuration.

Environment markers:
- @pytest.mark.openshift_only - Test only runs on OpenShift
- @pytest.mark.kind_only - Test only runs on Kind cluster
- @pytest.mark.requires_features(["feature1", "feature2"]) - Test requires specific features
- @pytest.mark.observability - Test should run AFTER other tests (for traffic analysis)

Running tests in two phases:
    # Phase 1: Run all tests except observability (generates traffic)
    pytest kagenti/tests/e2e/ -v -m "not observability"

    # Phase 2: Run observability tests (validates traffic patterns)
    pytest kagenti/tests/e2e/ -v -m "observability"
"""

import base64
import os
import pathlib
import subprocess
import tempfile
from uuid import uuid4

import httpx
import pytest
import yaml


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "openshift_only: Test only runs on OpenShift environment"
    )
    config.addinivalue_line(
        "markers", "kind_only: Test only runs on Kind cluster environment"
    )
    config.addinivalue_line(
        "markers",
        "requires_features(features): Test requires specific features to be enabled",
    )
    config.addinivalue_line(
        "markers",
        "observability: Test should run AFTER other tests (for traffic analysis)",
    )


def _warmup_agent(agent_url: str, verify_ssl=False) -> bool:
    """Send a throwaway message to warm up an agent's LLM connection.

    The first LLM call after agent restart is slow (model loading, connection
    pool init). Sending a warmup request before real tests prevents cold-start
    timeouts in test_shell_ls and other early tests.
    """
    import json

    payload = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Run the command: echo warmup"}],
                "messageId": uuid4().hex,
                "contextId": f"warmup-{uuid4().hex[:8]}",
            }
        },
    }
    try:
        with httpx.Client(
            timeout=120.0, verify=verify_ssl, follow_redirects=True
        ) as client:
            with client.stream(
                "POST",
                f"{agent_url}/",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        result = event.get("result", {})
                        status = result.get("status", {})
                        state = (
                            status.get("state", "") if isinstance(status, dict) else ""
                        )
                        if state in ("completed", "failed", "canceled"):
                            return True
    except Exception:
        pass
    return False


@pytest.fixture(scope="session")
def warmup_sandbox_agents():
    """Warm up sandbox agents before any tests run.

    Sends a throwaway echo command to each agent variant so the first
    real test doesn't hit the cold-start penalty (model loading, DB
    connection pool init).
    """
    if not os.getenv("ENABLE_SANDBOX_TESTS", ""):
        config_file = os.getenv("KAGENTI_CONFIG_FILE", "")
        if not config_file:
            return
        try:
            p = pathlib.Path(config_file)
            if not p.is_absolute():
                p = pathlib.Path(__file__).parent.parent.parent.parent / config_file
            cfg = yaml.safe_load(p.read_text())
            flags = (
                cfg.get("charts", {})
                .get("kagenti", {})
                .get("values", {})
                .get("featureFlags", {})
            )
            if not flags.get("sandbox"):
                return
        except Exception:
            return

    agents = ["sandbox-legion", "sandbox-basic"]
    namespace = os.getenv("SANDBOX_NAMESPACE", "team1")
    for agent in agents:
        env_key = f"SANDBOX_{agent.split('-', 1)[-1].upper()}_URL"
        url = os.getenv(env_key, f"http://{agent}.{namespace}.svc.cluster.local:8000")
        card_ok = False
        try:
            resp = httpx.get(
                f"{url}/.well-known/agent-card.json",
                timeout=5.0,
                verify=False,
                follow_redirects=True,
            )
            card_ok = resp.status_code == 200
        except Exception:
            pass
        if card_ok:
            _warmup_agent(url, verify_ssl=False)


# Module-level cache for test session ID (shared across all tests)
_test_session_id_cache = None


@pytest.fixture(scope="session")
def test_session_id():
    """
    Generate a unique session ID for this test run.

    This ID is used to correlate traces across tests:
    - Agent conversation tests send this as context_id
    - Observability tests filter traces by gen_ai.conversation.id or mlflow.trace.session

    Using a shared session ID prevents false positives from old traces when running
    repeated test runs on the same cluster.
    """
    global _test_session_id_cache

    # Use cached value to ensure all tests use the same ID
    if _test_session_id_cache is None:
        _test_session_id_cache = str(uuid4())
        print(f"\n[Session ID] Generated test session ID: {_test_session_id_cache}")

    return _test_session_id_cache


@pytest.fixture(scope="session")
def kagenti_config():
    """
    Load Kagenti installer configuration from YAML file.

    Reads from KAGENTI_CONFIG_FILE environment variable.
    If not set, returns None (tests will use defaults or skip).
    """
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        return None

    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        # Resolve relative to repo root
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent
        config_path = repo_root / config_file

    if not config_path.exists():
        # Config file specified but not found - return None instead of failing
        # This allows tests to run with defaults when config is missing
        return None

    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def enabled_features(kagenti_config):
    """
    Extract enabled feature flags from config.

    Returns dict like: {'keycloak': True, 'spire': True, 'platform_operator': True, ...}
    Treats operators as features for unified handling.

    Extracts features from ALL layers of the config:
    - Top-level enabled flags (gatewayApi, certManager, tekton, kiali, etc.)
    - charts.*.enabled
    - charts.*.values.components.*
    """
    if not kagenti_config:
        return {}

    features = {}

    # ===== Top-level enabled flags =====
    top_level_features = [
        "gatewayApi",
        "certManager",
        "tekton",
        "kiali",
        "rhoai",
    ]
    for feature in top_level_features:
        if feature in kagenti_config:
            features[feature] = kagenti_config[feature].get("enabled", False)

    # ===== Chart-level enabled flags =====
    charts = kagenti_config.get("charts", {})

    # Each chart can have an enabled flag
    for chart_name, chart_config in charts.items():
        if isinstance(chart_config, dict) and "enabled" in chart_config:
            # Store as chart name (e.g., "istio", "mcpGateway")
            features[chart_name] = chart_config["enabled"]

    # ===== Component-level enabled flags =====

    # Check charts.kagenti-deps.values.components
    deps_chart = charts.get("kagenti-deps", {})
    deps_components = deps_chart.get("values", {}).get("components", {})

    for component_name, component_config in deps_components.items():
        if isinstance(component_config, dict) and "enabled" in component_config:
            features[component_name] = component_config["enabled"]

    # Check charts.kagenti.values.components (includes operators)
    kagenti_chart = charts.get("kagenti", {})
    components = kagenti_chart.get("values", {}).get("components", {})

    for component_name, component_config in components.items():
        if isinstance(component_config, dict) and "enabled" in component_config:
            features[component_name] = component_config["enabled"]

    return features


@pytest.fixture(scope="session")
def is_openshift(kagenti_config):
    """
    Detect if running on OpenShift based on config.

    Checks for openshift: true in various config locations:
    - charts.kagenti-deps.values.openshift
    - charts.kagenti.values.openshift
    - Top-level openshift flag

    Returns True if any of these are set to True.
    """
    if not kagenti_config:
        return False

    # Check top-level
    if kagenti_config.get("openshift", False):
        return True

    # Check chart values
    charts = kagenti_config.get("charts", {})

    # kagenti-deps
    deps_chart = charts.get("kagenti-deps", {})
    if deps_chart.get("values", {}).get("openshift", False):
        return True

    # kagenti
    kagenti_chart = charts.get("kagenti", {})
    if kagenti_chart.get("values", {}).get("openshift", False):
        return True

    return False


def _fetch_openshift_ingress_ca():
    """
    Fetch OpenShift ingress CA certificate from the cluster.

    Tries multiple sources in priority order:
    1. kube-root-ca.crt from kagenti-system (always accessible on hosted clusters)
    2. kube-root-ca.crt from openshift-config (management cluster)

    Returns the path to a temporary CA bundle file, or None if not available.
    """
    # Sources to try in priority order
    sources = [
        # kagenti-system is always accessible (even on HyperShift hosted clusters)
        ("configmap", "kube-root-ca.crt", "kagenti-system", "{.data.ca\\.crt}", False),
        # openshift-config may not be accessible on hosted clusters
        (
            "configmap",
            "kube-root-ca.crt",
            "openshift-config",
            "{.data.ca\\.crt}",
            False,
        ),
    ]

    for resource_type, name, namespace, jsonpath, needs_base64 in sources:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    resource_type,
                    name,
                    "-n",
                    namespace,
                    "-o",
                    f"jsonpath={jsonpath}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0 or not result.stdout:
                continue

            ca_cert = result.stdout
            if needs_base64:
                import base64

                ca_cert = base64.b64decode(ca_cert).decode("utf-8")

            if not ca_cert.startswith("-----BEGIN CERTIFICATE-----"):
                continue

            # Write to a temporary file (will be cleaned up when process exits)
            ca_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".crt", delete=False, prefix="openshift-ingress-ca-"
            )
            ca_file.write(ca_cert)
            ca_file.close()

            return ca_file.name

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    return None


# Module-level cache for the CA file path
_openshift_ca_file_cache = None


@pytest.fixture(scope="session")
def openshift_ingress_ca(is_openshift):
    """
    Get the OpenShift ingress CA certificate file path.

    Fetches the cluster root CA from kube-root-ca.crt configmap and writes
    it to a temp file. Returns the path to the CA bundle file, or None if
    not on OpenShift.

    On OpenShift, this fixture MUST succeed - tests should never fall back
    to verify=False. If the CA cannot be fetched, tests will fail.

    The CA file is cached for the session to avoid repeated kubectl calls.
    """
    global _openshift_ca_file_cache

    if not is_openshift:
        return None

    # Check environment variable first (allows override)
    ca_path = os.getenv("OPENSHIFT_INGRESS_CA")
    if ca_path and pathlib.Path(ca_path).exists():
        return ca_path

    # Use cached value if available
    if _openshift_ca_file_cache is not None:
        return _openshift_ca_file_cache

    # Fetch from cluster
    _openshift_ca_file_cache = _fetch_openshift_ingress_ca()

    if _openshift_ca_file_cache is None:
        pytest.fail(
            "Could not fetch OpenShift ingress CA certificate. "
            "Tried kube-root-ca.crt from kagenti-system and openshift-config. "
            "Set OPENSHIFT_INGRESS_CA env var to the CA bundle path as a workaround."
        )

    return _openshift_ca_file_cache


@pytest.fixture(scope="session")
def http_client(is_openshift, openshift_ingress_ca):
    """
    Create an httpx AsyncClient configured for the environment.

    On OpenShift: Uses ssl.SSLContext with the ingress CA certificate
    On Kind: Standard SSL verification (HTTP, no TLS)
    """
    if is_openshift:
        import ssl

        ssl_ctx = ssl.create_default_context(cafile=openshift_ingress_ca)
        return httpx.AsyncClient(verify=ssl_ctx, follow_redirects=False)
    else:
        return httpx.AsyncClient(follow_redirects=False)


def _discover_backend_url_from_route():
    """
    Try to discover the backend URL from an OpenShift Route.

    Tries multiple route names in priority order:
    1. kagenti-ui - the UI route that proxies /api/* to the backend
    2. kagenti-api - a dedicated API route (used by some deployments)

    Returns the URL string or None if no route is found.
    """
    route_names = ["kagenti-ui", "kagenti-api"]

    for route_name in route_names:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "route",
                    route_name,
                    "-n",
                    "kagenti-system",
                    "-o",
                    "jsonpath={.spec.host}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"https://{result.stdout.strip()}"
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    return None


@pytest.fixture(scope="session")
def backend_url(is_openshift):
    """
    Get the backend API URL based on environment.

    Discovery order:
    1. KAGENTI_BACKEND_URL env var (explicit override)
    2. OpenShift Route auto-discovery (tries kagenti-ui and kagenti-api routes)
    3. Kind-style localhost fallback (port-forward on localhost:8002)

    The OpenShift route discovery runs regardless of the is_openshift config flag,
    because on HyperShift clusters the config file may not be set even though the
    cluster is OpenShift-based.
    """
    # 1. Explicit env var
    url = os.environ.get("KAGENTI_BACKEND_URL")
    if url:
        return url.rstrip("/")

    # 2. Try OpenShift route auto-discovery (works on any OpenShift/HyperShift cluster)
    route_url = _discover_backend_url_from_route()
    if route_url:
        return route_url

    # 3. If is_openshift is True but no route was found, fail explicitly
    if is_openshift:
        pytest.fail(
            "Running on OpenShift but could not discover kagenti-ui or kagenti-api "
            "route in kagenti-system namespace. "
            "Set KAGENTI_BACKEND_URL env var as a workaround."
        )

    # 4. Kind cluster with port-forward (port 8002 to avoid conflict with weather-service)
    return "http://localhost:8002"


def _detect_openshift_from_config(kagenti_config):
    """Helper to detect OpenShift from config dict."""
    if not kagenti_config:
        return False

    if kagenti_config.get("openshift", False):
        return True

    charts = kagenti_config.get("charts", {})

    deps_chart = charts.get("kagenti-deps", {})
    if deps_chart.get("values", {}).get("openshift", False):
        return True

    kagenti_chart = charts.get("kagenti", {})
    if kagenti_chart.get("values", {}).get("openshift", False):
        return True

    return False


def pytest_collection_modifyitems(config, items):
    """
    Skip tests at collection time based on required features.

    This allows using decorators like @pytest.mark.requires_features(["platformOperator"])
    instead of runtime pytest.skip() calls.

    Uses positive condition: tests declare what features they REQUIRE, not what they exclude.
    """
    # Read config file at collection time (before fixtures are available)
    config_file = os.getenv("KAGENTI_CONFIG_FILE")
    if not config_file:
        # No config specified - don't skip any tests
        return

    config_path = pathlib.Path(config_file)
    if not config_path.is_absolute():
        # Resolve relative to repo root (same logic as kagenti_config fixture)
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent
        config_path = repo_root / config_file

    if not config_path.exists():
        # Config file doesn't exist - don't skip any tests
        return

    try:
        with open(config_path) as f:
            kagenti_config = yaml.safe_load(f)
    except Exception:
        # Failed to load config - don't skip any tests
        return

    # Build enabled features dict (same logic as enabled_features fixture)
    enabled = {}

    # ===== Top-level enabled flags =====
    top_level_features = [
        "gatewayApi",
        "certManager",
        "tekton",
        "kiali",
        "rhoai",
    ]
    for feature in top_level_features:
        if feature in kagenti_config:
            enabled[feature] = kagenti_config[feature].get("enabled", False)

    # ===== Chart-level enabled flags =====
    charts = kagenti_config.get("charts", {})

    # Each chart can have an enabled flag
    for chart_name, chart_config in charts.items():
        if isinstance(chart_config, dict) and "enabled" in chart_config:
            enabled[chart_name] = chart_config["enabled"]

    # ===== Component-level enabled flags =====

    # deps components
    deps_chart = charts.get("kagenti-deps", {})
    deps_components = deps_chart.get("values", {}).get("components", {})

    for component_name, component_config in deps_components.items():
        if isinstance(component_config, dict) and "enabled" in component_config:
            # Use OR logic: if any chart enables a feature, it stays enabled
            # (e.g., istio enabled in kagenti-deps but disabled in kagenti chart)
            enabled[component_name] = (
                enabled.get(component_name, False) or component_config["enabled"]
            )

    # kagenti components (includes operators)
    kagenti_chart = charts.get("kagenti", {})
    components = kagenti_chart.get("values", {}).get("components", {})

    for component_name, component_config in components.items():
        if isinstance(component_config, dict) and "enabled" in component_config:
            enabled[component_name] = (
                enabled.get(component_name, False) or component_config["enabled"]
            )

    # ===== Feature flags =====
    # Feature flags from charts.kagenti.values.featureFlags (sandbox, integrations, etc.)
    feature_flags = kagenti_chart.get("values", {}).get("featureFlags", {})
    for flag_name, flag_value in feature_flags.items():
        if isinstance(flag_value, bool):
            enabled[flag_name] = enabled.get(flag_name, False) or flag_value

    # Environment variable overrides (ENABLE_SANDBOX_TESTS etc.)
    if os.getenv("ENABLE_SANDBOX_TESTS"):
        enabled["sandbox"] = True

    # Runtime override: disable rhoai tests when CRDs aren't present
    if os.getenv("ENABLE_RHOAI_TESTS", "").lower() == "false":
        enabled["rhoai"] = False
    elif enabled.get("rhoai"):
        try:
            from kubernetes import client as _k8s_client

            api = _k8s_client.ApiextensionsV1Api()
            api.read_custom_resource_definition(
                "datascienceclusters.datasciencecluster.opendatahub.io"
            )
        except Exception:
            enabled["rhoai"] = False

    # Detect OpenShift from config
    is_openshift = _detect_openshift_from_config(kagenti_config)

    # Process each test item
    for item in items:
        # Check for @pytest.mark.openshift_only marker
        if item.get_closest_marker("openshift_only"):
            if not is_openshift:
                item.add_marker(
                    pytest.mark.skip(reason="Test requires OpenShift environment")
                )

        # Check for @pytest.mark.kind_only marker
        if item.get_closest_marker("kind_only"):
            if is_openshift:
                item.add_marker(
                    pytest.mark.skip(reason="Test requires Kind environment")
                )

        # Check for @pytest.mark.requires_features(["feature1", "feature2"]) marker
        marker = item.get_closest_marker("requires_features")
        if marker:
            # Extract required features from marker (positive condition: what IS required)
            required_features = marker.args[0] if marker.args else []

            # Normalize to list if single string
            if isinstance(required_features, str):
                required_features = [required_features]

            # Check if all required features are enabled
            missing_features = [
                feature
                for feature in required_features
                if not enabled.get(feature, False)
            ]

            # Skip if any required feature is missing
            if missing_features:
                skip_reason = (
                    f"Test requires features: {required_features} "
                    f"(missing: {missing_features})"
                )
                item.add_marker(pytest.mark.skip(reason=skip_reason))
