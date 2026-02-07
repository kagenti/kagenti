# Kiali Validation - Implementation Plan

See [docs/kiali/README.md](docs/kiali/README.md) for full documentation.

## Current Status

- [x] KialiClient with auto-detection (OpenShift route / Kind ingress)
- [x] Istio configuration validation (errors + warnings)
- [x] Traffic error detection with configurable threshold
- [x] mTLS compliance check for all traffic edges
- [x] Comprehensive traffic report with per-edge pass/fail
- [x] 2h traffic analysis window (configurable)
- [x] Standalone CLI mode for debugging
- [x] Two-phase test execution (traffic generation + validation)
- [x] CI integration in 90-run-e2e-tests.sh
- [x] Official documentation with architecture diagrams

## Pending

- [ ] Run on live HyperShift cluster and iterate on failures
- [ ] Validate Kiali API response format matches expected schema
- [ ] Add expected traffic topology validation (Future Phase 1)
- [ ] Add baseline/delta mode (Future Phase 2)

## Iteration Log

| DateTime | Cluster | Commit | Pass | Fail | Skip | Notes |
|----------|---------|--------|------|------|------|-------|
| _pending_ | _TBD_ | _TBD_ | - | - | - | First run on live cluster |
