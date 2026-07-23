---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Istio Multi-Mesh Shared Trust via cert-manager

> **[Historical — Ansible installer removed]** This design doc references the Ansible installer
> (`deployments/ansible/`) which has been removed. The cert-manager Helm resources are in place;
> the cacerts transformation step is now handled by the OCP installer (`scripts/ocp/setup-rossoctl.sh`).

**Date:** 2026-03-08
**Status:** Approved
**Replaces:** Shared Trust Pattern (credential copying workaround)

## Problem

When RHOAI 3.x is installed alongside Rossoctl, two Istio control planes exist:
- `default` (Rossoctl, ambient mode) in `istio-system`
- `openshift-gateway` (RHOAI, gateway-only) in `openshift-ingress`

Both istiods create `istio-ca-root-cert` ConfigMaps in watched namespaces using
different self-signed CAs. The `openshift-gateway` istiod watches ALL namespaces
(no discoverySelectors, RHOAI operator reconciles them back). This causes a race
condition where workload proxies (e.g., `mcp-gateway-istio`) get the wrong CA and
crash with `x509: certificate signed by unknown authority`.

The previous workaround copied CA secrets between namespaces — a security
anti-pattern that doesn't scale.

## Solution

Use cert-manager (already deployed on OCP) to create a shared root CA and
generate intermediate CA certificates for both istiods via the Istio `cacerts`
Secret mechanism.

Key properties:
- Both istiods auto-detect `cacerts` Secret on startup (standard Istio behavior)
- No Istio CR modifications needed (RHOAI operator cannot interfere)
- cert-manager handles CA rotation automatically
- No credential copying — each istiod has its own intermediate key

## Architecture

```
cert-manager
  |
  +- SelfSigned ClusterIssuer: istio-mesh-root-selfsigned
  |     +- Certificate: istio-mesh-root-ca (in rossoctl-system)
  |           +- Secret: istio-mesh-root-ca-secret
  |
  +- CA ClusterIssuer: istio-mesh-ca (uses istio-mesh-root-ca-secret)
  |     |
  |     +- Certificate: istio-cacerts-default (in istio-system)
  |     |     +- Secret: cacerts <- Rossoctl istiod reads this
  |     |
  |     +- Certificate: istio-cacerts-openshift-gateway (in openshift-ingress)
  |           +- Secret: cacerts <- RHOAI istiod reads this
  |
  +- Both secrets contain same root-cert.pem
       -> ConfigMap race is harmless (same root of trust)
       -> cert-manager auto-rotates intermediate certs
```

## Istio cacerts Secret Format

Istio expects a secret named `cacerts` in the istiod namespace with these keys:
- `ca-cert.pem` — intermediate signing certificate
- `ca-key.pem` — intermediate signing key
- `root-cert.pem` — root certificate (shared across all istiods)
- `cert-chain.pem` — certificate chain (intermediate + root)

cert-manager Certificate resources generate `tls.crt` and `tls.key`. We need
to map these to Istio's expected key names using cert-manager's
`additionalOutputFormats` or a post-processing step.

## Scope

- Only active when `rhoai.enabled: true` (no effect on non-RHOAI deployments)
- Only on OpenShift (requires cert-manager operator)
- Replaces the Shared Trust Pattern workaround entirely

## Files

### New
- `charts/rossoctl-deps/templates/rhoai-shared-trust.yaml`

### Modified
- `deployments/ansible/roles/rossoctl_installer/tasks/05_install_rhoai.yaml`
- `deployments/ansible/roles/rossoctl_installer/tasks/main.yml`

## References

- [Istio Plug-in CA Certificates](https://istio.io/latest/docs/tasks/security/cert-management/plugin-ca-cert/)
- [OSSM 3.x cert-manager integration](https://docs.redhat.com/en/documentation/red_hat_openshift_service_mesh/3.1/html/installing/ossm-cert-manager)
- [cert-manager istio-csr](https://github.com/cert-manager/istio-csr)
- [OSSM 3 multiple meshes](https://docs.redhat.com/en/documentation/red_hat_openshift_service_mesh/3.0/html/installing/ossm-deploying-multiple-service-meshes-on-single-cluster)
