# Kiali E2E Tests and Service Mesh Validation Scans

This document describes the Kiali-based Istio configuration and traffic
validation in the Kagenti HyperShift OpenShift CI E2E tests.

## Overview

Kiali provides comprehensive service mesh observability including:

1. **Istio configuration validation** - Detects misconfigurations in VirtualServices,
   DestinationRules, etc.
2. **Traffic health monitoring** - Tracks HTTP error rates between services
3. **mTLS compliance** - Verifies all traffic uses mutual TLS

These tests are marked with `@pytest.mark.observability` and run AFTER other
E2E tests to validate both static configuration and traffic patterns.

## Test Execution

### Two-Phase Approach

Run pytest twice in the same CI step to ensure observability tests run after
traffic-generating tests:

```bash
# Phase 1: All tests EXCEPT observability (generates traffic)
pytest kagenti/tests/e2e/ -v -m "not observability"

# Phase 2: ONLY observability tests (validates traffic patterns)
pytest kagenti/tests/e2e/ -v -m "observability"
```

### CI Integration

The HyperShift E2E pipeline should run both phases sequentially in
`.github/scripts/kagenti-operator/90-run-e2e-tests.sh`:

```bash
# Phase 1: Run all tests except observability (generates traffic)
pytest kagenti/tests/e2e/ -v -m "not observability"

# Phase 2: Run observability tests (validates traffic from phase 1)
pytest kagenti/tests/e2e/ -v -m "observability"
```

The test is automatically skipped if Kiali is not enabled in the config
(`@pytest.mark.requires_features(["kiali"])`).

## Test Coverage

### test_kiali_connectivity

Verifies Kiali is accessible and running. Skips all other tests if Kiali
is unavailable.

### test_no_istio_configuration_issues

Scans for Istio configuration errors and warnings:

- **Errors**: Always fail the test
- **Warnings**: Fail by default (configurable via `KIALI_FAIL_ON_WARNINGS=false`)

### test_no_traffic_errors

Analyzes traffic graph from the last N minutes (default 10m):

- Fails if any service-to-service edge has error rate > threshold (default 1%)
- Validates that E2E tests completed without HTTP 5xx errors

### test_mtls_compliance

Verifies all service mesh traffic uses mutual TLS:

- Fails if ANY edge is not using mTLS
- Critical for zero-trust security validation

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KIALI_URL` | Override Kiali URL | Auto-detect from cluster |
| `KIALI_NAMESPACES` | Comma-separated namespaces to scan | See DEFAULT_NAMESPACES |
| `KIALI_IGNORE_NAMESPACES` | Namespaces to skip | OpenShift AI, GPU operator |
| `KIALI_SKIP_VALIDATION_CODES` | Validation codes to ignore | None |
| `KIALI_FAIL_ON_WARNINGS` | Fail on warnings (true/false) | true |
| `KIALI_TRAFFIC_DURATION` | Duration for traffic analysis | 10m |
| `KIALI_ERROR_RATE_THRESHOLD` | Max allowed error rate (0.0-1.0) | 0.01 |

## Default Namespaces Scanned

```python
DEFAULT_NAMESPACES = [
    "kagenti-system",
    "gateway-system",
    "mcp-system",
    "team1",
    "team2",
    "keycloak",
    "spire-server",
    "spire-system",
    "spire-mgmt",
    "toolhive-system",
    "istio-system",
    "istio-ztunnel",
]
```

## Default Ignored Namespaces

```python
DEFAULT_IGNORE_NAMESPACES = [
    "redhat-ods-applications",  # OpenShift AI
    "redhat-ods-operator",
    "redhat-ods-monitoring",
    "nvidia-gpu-operator",
    "openshift-nfd",
]
```

## Sample Output

### Configuration Validation Report

```text
======================================================================
 Kiali Validation Report
======================================================================

ERRORS (1)
----------------------------------------------------------------------
  [ERROR] team1/VirtualService/weather-service: KIA1106 - Route references undefined destination

WARNINGS (2)
----------------------------------------------------------------------
  [WARNING] kagenti-system/DestinationRule/kagenti-ui: KIA0201 - Host not found
  [WARNING] mcp-system/Gateway/mcp-gateway: KIA0301 - No matching VirtualService

SUMMARY
----------------------------------------------------------------------
  Total errors:   1
  Total warnings: 2
  Namespaces with errors: ['team1']
  Namespaces with warnings: ['kagenti-system', 'mcp-system']
======================================================================
```

### Traffic Health Report

```text
======================================================================
 Traffic Health Report
======================================================================

EDGES WITH ERRORS (1)
----------------------------------------------------------------------
  team1/weather-agent -> team1/weather-tool [http] 150 reqs, 5.3% errors, mTLS

TRAFFIC SUMMARY
----------------------------------------------------------------------
  Namespaces analyzed: ['kagenti-system', 'team1', 'mcp-system']
  Total edges:         12
  Total requests:      1847
  Edges with errors:   1
  Edges without mTLS:  0
  Max error rate:      5.33%
======================================================================
```

## Standalone Script

The test file can also run as a standalone script for debugging:

```bash
# Basic validation scan
python kagenti/tests/e2e/test_kiali_validations.py

# With traffic analysis
python kagenti/tests/e2e/test_kiali_validations.py --check-traffic --duration 30m

# JSON output for CI integration
python kagenti/tests/e2e/test_kiali_validations.py --json --check-traffic

# Custom error threshold
python kagenti/tests/e2e/test_kiali_validations.py --check-traffic --error-threshold 0.05
```

## Common Kiali Validation Codes

| Code | Severity | Description |
|------|----------|-------------|
| KIA0101 | Warning | No matching workload found for this service |
| KIA0201 | Warning | This host has no matching entry in the service registry |
| KIA0301 | Warning | No matching Gateway for this VirtualService |
| KIA1001 | Error | DestinationRule with no matching workloads |
| KIA1106 | Error | VirtualService references undefined route |
| KIA1201 | Error | PeerAuthentication with invalid selector |

See [Kiali Validation Documentation](https://kiali.io/docs/features/validations/)
for complete list.

## Future Enhancements

### Phase 1: GitHub Actions Integration (Priority: High)

- [ ] Add GitHub Actions workflow annotations for validation failures
- [ ] Output validation issues as GitHub check annotations
- [ ] Create summary table in GitHub Actions job summary

### Phase 2: Expected Traffic Validation (Priority: Medium)

- [ ] Define expected service-to-service traffic patterns
- [ ] Verify expected routes exist (e.g., weather-agent → weather-tool)
- [ ] Alert on unexpected traffic patterns

### Phase 3: Baseline/Delta Mode (Priority: Medium)

- [ ] Store baseline validation state in git
- [ ] Only fail on NEW issues (delta from baseline)
- [ ] Command to update baseline after intentional changes

### Phase 4: Response Time Validation (Priority: Low)

- [ ] Warn if p99 latency exceeds threshold
- [ ] Track response time trends across runs

## Known Issues

### OpenShift AI Namespace

The `redhat-ods-applications` namespace has known PeerAuthentication issues that
are managed by the OpenShift AI operator. These are ignored by default.

### Self-Signed Certificates

On HyperShift clusters, the Kiali route uses self-signed certificates. The test
handles this by disabling SSL verification for the Kiali API calls.

### No Traffic Observed

If `test_no_traffic_errors` reports "No traffic observed", ensure:

1. Other E2E tests ran successfully before this test
2. The traffic duration is long enough (increase with `KIALI_TRAFFIC_DURATION=30m`)
3. Prometheus/Kiali metrics collection is working

## Troubleshooting

### Test Skipped

If the test is skipped with "Test requires features: ['kiali']":

- Check that `kiali.enabled: true` in your config file
- Verify `KAGENTI_CONFIG_FILE` points to correct config

### Cannot Connect to Kiali

If the test fails with "Cannot connect to Kiali":

- Verify Kiali pod is running: `kubectl get pods -n istio-system`
- Check Kiali route exists: `oc get route kiali -n istio-system`
- Test connectivity: `curl -k https://$(oc get route kiali -n istio-system -o jsonpath='{.spec.host}')/api/status`

### Authentication Failures

If getting 401/403 errors:

- Ensure you're logged in: `oc whoami`
- Check token is valid: `oc whoami -t`
- Verify RBAC permissions for Kiali API access

## References

- [Kiali Validation Feature](https://kiali.io/docs/features/validations/)
- [Kiali API Documentation](https://kiali.io/docs/configuration/kialis.kiali.io/)
- [Kiali Graph API](https://kiali.io/docs/features/topology/)
- [Istio Configuration Best Practices](https://istio.io/latest/docs/ops/best-practices/)
