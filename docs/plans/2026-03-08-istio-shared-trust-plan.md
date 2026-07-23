---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Istio Shared Trust Implementation Plan

> **[Historical — Ansible installer removed]** This plan contains references to the Ansible installer
> (`deployments/ansible/`) which has been removed. The Helm chart now handles shared trust setup
> directly, and OCP installs use `scripts/ocp/setup-rossoctl.sh`.

<!-- markdownlint-disable-next-line MD028 -->

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Shared Trust Pattern workaround with proper cert-manager-based shared CA for dual Istio control planes (Rossoctl + RHOAI).

**Architecture:** cert-manager generates a shared root CA and intermediate certificates. A Helm template creates the cert-manager resources (ClusterIssuers, Certificates). An Ansible task transforms the cert-manager secrets into Istio's `cacerts` format and restarts both istiods. Both istiods auto-detect the shared CA, eliminating the ConfigMap race condition. [Note: Ansible installer removed; this logic is now in the Helm chart]

**Tech Stack:** cert-manager (Certificate, ClusterIssuer), Kubernetes Secrets, Helm templates

**Design doc:** `docs/plans/2026-03-08-istio-shared-trust-design.md`

---

### Task 1: Create cert-manager Shared Trust Helm Template

**Files:**
- Create: `charts/rossoctl-deps/templates/rhoai-shared-trust.yaml`

**Step 1: Create the Helm template**

This template creates cert-manager resources to generate a shared root CA and intermediate certificates for both Istio control planes. Gated by `components.rhoai.enabled` and `openshift`.

```yaml
{{- if and .Values.components.rhoai.enabled .Values.openshift }}
{{- /*
  Istio Multi-Mesh Shared Trust via cert-manager

  When RHOAI is installed alongside Rossoctl, two Istio control planes exist
  (default + openshift-gateway) with different self-signed CAs. This creates
  a shared root CA so both istiods trust each other's workload certificates.

  cert-manager generates:
  1. A self-signed root CA
  2. An intermediate CA Certificate for each istiod namespace

  Ansible (05_install_rhoai.yaml) transforms these into Istio cacerts format
  and restarts both istiods to pick up the shared CA.
*/}}
---
# Step 1: Self-signed issuer to bootstrap the root CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: istio-mesh-root-selfsigned
  labels:
    {{- include "rossoctl.labels" . | nindent 4 }}
spec:
  selfSigned: {}
---
# Step 2: Root CA certificate (self-signed)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-mesh-root-ca
  namespace: {{ .Values.rhoai.trustNamespace | default "rossoctl-system" }}
  labels:
    {{- include "rossoctl.labels" . | nindent 4 }}
spec:
  isCA: true
  commonName: istio-mesh-root-ca
  duration: 87600h  # 10 years
  renewBefore: 720h  # 30 days
  secretName: istio-mesh-root-ca-secret
  privateKey:
    algorithm: RSA
    size: 4096
  issuerRef:
    name: istio-mesh-root-selfsigned
    kind: ClusterIssuer
---
# Step 3: CA issuer using the root CA (signs intermediate certs)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: istio-mesh-ca
  labels:
    {{- include "rossoctl.labels" . | nindent 4 }}
spec:
  ca:
    secretName: istio-mesh-root-ca-secret
---
# Step 4: Intermediate CA for Rossoctl istiod (istio-system)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-cacerts-default
  namespace: istio-system
  labels:
    {{- include "rossoctl.labels" . | nindent 4 }}
spec:
  isCA: true
  commonName: istio-ca-default
  duration: 8760h  # 1 year
  renewBefore: 720h  # 30 days
  secretName: istio-cacerts-default-cert
  privateKey:
    algorithm: RSA
    size: 2048
  issuerRef:
    name: istio-mesh-ca
    kind: ClusterIssuer
---
# Step 5: Intermediate CA for RHOAI istiod (openshift-ingress)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-cacerts-openshift-gateway
  namespace: openshift-ingress
  labels:
    {{- include "rossoctl.labels" . | nindent 4 }}
spec:
  isCA: true
  commonName: istio-ca-openshift-gateway
  duration: 8760h  # 1 year
  renewBefore: 720h  # 30 days
  secretName: istio-cacerts-og-cert
  privateKey:
    algorithm: RSA
    size: 2048
  issuerRef:
    name: istio-mesh-ca
    kind: ClusterIssuer
{{- end }}
```

**Step 2: Commit**

```bash
git add charts/rossoctl-deps/templates/rhoai-shared-trust.yaml
git commit -s -m "feat: add cert-manager shared trust for dual Istio control planes"
```

---

### Task 2: Add Ansible cacerts Secret Creation and istiod Restart

> [Note: Ansible installer removed; this logic is now in the Helm chart]

**Files:**
- Modify: `deployments/ansible/roles/rossoctl_installer/tasks/05_install_rhoai.yaml`

**Step 1: Add cacerts transformation after DSC ready**

After the DataScienceCluster reaches Ready, add tasks that:
1. Wait for cert-manager to generate the intermediate CA secrets
2. Transform them from cert-manager format (`tls.crt`, `tls.key`, `ca.crt`) to Istio format (`ca-cert.pem`, `ca-key.pem`, `root-cert.pem`, `cert-chain.pem`)
3. Create `cacerts` Secrets in both istiod namespaces
4. Restart both istiods

Add after the DSC ready wait block, before the final `when: rhoai.enabled`:

```yaml
    # --- Shared Trust: cert-manager CA → Istio cacerts format ---
    # cert-manager generates intermediate CA certs with keys tls.crt/tls.key/ca.crt.
    # Istio expects a secret named "cacerts" with keys ca-cert.pem/ca-key.pem/
    # root-cert.pem/cert-chain.pem. Transform and create.

    - name: Wait for cert-manager to generate Rossoctl intermediate CA
      command: >-
        kubectl get secret istio-cacerts-default-cert -n istio-system
        -o jsonpath='{.data.tls\.crt}'
      register: rossoctl_cacert_check
      retries: 30
      delay: 10
      until: rossoctl_cacert_check.rc == 0 and rossoctl_cacert_check.stdout | length > 0
      changed_when: false

    - name: Wait for cert-manager to generate RHOAI intermediate CA
      command: >-
        kubectl get secret istio-cacerts-og-cert -n openshift-ingress
        -o jsonpath='{.data.tls\.crt}'
      register: rhoai_cacert_check
      retries: 30
      delay: 10
      until: rhoai_cacert_check.rc == 0 and rhoai_cacert_check.stdout | length > 0
      changed_when: false

    - name: Create cacerts secret for Rossoctl istiod (istio-system)
      shell: |
        # Read cert-manager generated certs
        CA_CERT=$(kubectl get secret istio-cacerts-default-cert -n istio-system -o jsonpath='{.data.tls\.crt}' | base64 -d)
        CA_KEY=$(kubectl get secret istio-cacerts-default-cert -n istio-system -o jsonpath='{.data.tls\.key}' | base64 -d)
        ROOT_CERT=$(kubectl get secret istio-cacerts-default-cert -n istio-system -o jsonpath='{.data.ca\.crt}' | base64 -d)
        CERT_CHAIN="${CA_CERT}
        ${ROOT_CERT}"

        # Create cacerts secret in Istio format
        kubectl create secret generic cacerts -n istio-system \
          --from-literal=ca-cert.pem="${CA_CERT}" \
          --from-literal=ca-key.pem="${CA_KEY}" \
          --from-literal=root-cert.pem="${ROOT_CERT}" \
          --from-literal=cert-chain.pem="${CERT_CHAIN}" \
          --dry-run=client -o yaml | kubectl apply -f -
      args:
        executable: /bin/bash

    - name: Create cacerts secret for RHOAI istiod (openshift-ingress)
      shell: |
        CA_CERT=$(kubectl get secret istio-cacerts-og-cert -n openshift-ingress -o jsonpath='{.data.tls\.crt}' | base64 -d)
        CA_KEY=$(kubectl get secret istio-cacerts-og-cert -n openshift-ingress -o jsonpath='{.data.tls\.key}' | base64 -d)
        ROOT_CERT=$(kubectl get secret istio-cacerts-og-cert -n openshift-ingress -o jsonpath='{.data.ca\.crt}' | base64 -d)
        CERT_CHAIN="${CA_CERT}
        ${ROOT_CERT}"

        kubectl create secret generic cacerts -n openshift-ingress \
          --from-literal=ca-cert.pem="${CA_CERT}" \
          --from-literal=ca-key.pem="${CA_KEY}" \
          --from-literal=root-cert.pem="${ROOT_CERT}" \
          --from-literal=cert-chain.pem="${CERT_CHAIN}" \
          --dry-run=client -o yaml | kubectl apply -f -
      args:
        executable: /bin/bash

    - name: Restart Rossoctl istiod to pick up shared CA
      command: kubectl rollout restart deployment/istiod -n istio-system
      register: rossoctl_istiod_restart

    - name: Restart RHOAI istiod to pick up shared CA
      command: kubectl rollout restart deployment/istiod-openshift-gateway -n openshift-ingress
      register: rhoai_istiod_restart

    - name: Wait for Rossoctl istiod rollout
      command: kubectl rollout status deployment/istiod -n istio-system --timeout=120s

    - name: Wait for RHOAI istiod rollout
      command: kubectl rollout status deployment/istiod-openshift-gateway -n openshift-ingress --timeout=120s

    - name: Delete stale CA ConfigMaps to force recreation with shared CA
      shell: |
        for ns in rossoctl-system gateway-system team1 team2 keycloak mcp-system; do
          kubectl delete configmap istio-ca-root-cert -n $ns --ignore-not-found 2>/dev/null
        done
      args:
        executable: /bin/bash
      failed_when: false

    - name: Restart ztunnel to pick up shared CA
      command: kubectl rollout restart daemonset/ztunnel -n istio-ztunnel
      failed_when: false

    - name: Wait for ztunnel rollout
      command: kubectl rollout status daemonset/ztunnel -n istio-ztunnel --timeout=300s
      failed_when: false
```

**Step 2: Commit**

```bash
git add deployments/ansible/roles/rossoctl_installer/tasks/05_install_rhoai.yaml
git commit -s -m "feat: transform cert-manager certs to Istio cacerts and restart istiods"
```

---

### Task 3: Remove Shared Trust Pattern Skip Condition

**Files:**
- Modify: `deployments/ansible/roles/rossoctl_installer/tasks/main.yml`

**Step 1: Update the Shared Trust Pattern block**

The existing Shared Trust Pattern block (copying CA secrets between namespaces) should be completely skipped when RHOAI is enabled, since the new cert-manager approach handles trust properly.

The current condition is:
```yaml
  when:
    - enable_openshift | default(false)
    - (charts['rossoctl-deps']...).istio.enabled | bool
    - not (rhoai.enabled | default(false))
```

This is already correct — when RHOAI is enabled, the old workaround is skipped and the new cert-manager approach (Task 2) handles trust instead. No change needed.

**Step 2: Update the comment block**

Replace the TODO comment above the Shared Trust Pattern to reference the new approach:

Find the comment starting with `# On OpenShift AI clusters (RHOAI 2.x)` and update to note that the proper solution is now implemented via cert-manager shared trust in `rhoai-shared-trust.yaml` and `05_install_rhoai.yaml`.

**Step 3: Commit**

```bash
git add deployments/ansible/roles/rossoctl_installer/tasks/main.yml
git commit -s -m "docs: update Shared Trust Pattern comments to reference cert-manager solution"
```

---

### Task 4: Update E2E Tests for Shared Trust Validation

**Files:**
- Modify: `rossoctl/tests/e2e/common/test_rhoai_integration.py`

**Step 1: Update the ztunnel test to also verify shared CA**

Add a test that verifies both istiods use the same root CA:

```python
    @pytest.mark.requires_features(["rhoai", "istio"])
    def test_shared_root_ca(self, k8s_client):
        """Verify both Istio control planes share the same root CA."""
        # Read CA ConfigMaps from two different namespaces
        cm_rossoctl = k8s_client.read_namespaced_config_map(
            name="istio-ca-root-cert",
            namespace="rossoctl-system",
        )
        cm_gateway = k8s_client.read_namespaced_config_map(
            name="istio-ca-root-cert",
            namespace="gateway-system",
        )
        rossoctl_ca = cm_rossoctl.data.get("root-cert.pem", "")
        gateway_ca = cm_gateway.data.get("root-cert.pem", "")
        assert rossoctl_ca == gateway_ca, (
            "Root CA mismatch between rossoctl-system and gateway-system. "
            "Both Istio control planes should share the same root CA."
        )
```

**Step 2: Commit**

```bash
git add rossoctl/tests/e2e/common/test_rhoai_integration.py
git commit -s -m "test: add shared root CA verification for dual Istio control planes"
```

---

### Task 5: Integration Test on HyperShift

**Step 1: Deploy on rossoctl-team-rho2 cluster**

```bash
cd /Users/ladas/Projects/OCTO/rossoctl/rossoctl
source .env.rossoctl-team
export PATH="/opt/homebrew/Cellar/helm@3/3.20.0/bin:$PATH"
KUBECONFIG=~/clusters/hcp/rossoctl-team-rho2/auth/kubeconfig \
  .claude/worktrees/rhoai-integration/.github/scripts/local-setup/hypershift-full-test.sh rho2 \
  --skip-cluster-create --skip-cluster-destroy --include-rossoctl-install --include-test --env ocp
```

**Step 2: Verify**

- `mcp-gateway-istio` pod starts WITHOUT CrashLoopBackOff
- `test_shared_root_ca` passes
- `test_ztunnel_no_bad_signature` passes
- All existing tests pass

**Step 3: Commit any fixes**

```bash
git commit -s -m "fix: address integration test findings for shared trust"
```
