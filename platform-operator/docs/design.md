# Kagenti Installation Simplification — Implementation Plan

## Context

Kagenti's current installer is a 1983-line Ansible playbook (`deployments/ansible/roles/kagenti_installer/tasks/main.yml`) that orchestrates 29+ sequential steps across Helm charts, kubectl applies, OLM subscriptions, and post-install fixups. This plan migrates to a Kubernetes-native architecture based on the [Platform Operator Migration Design V9.1](https://docs.google.com/document/d/1gz59GpkdIdberZo2GPk7VQxvooW_eZu_Pmx4_rei3mM) with refinements from CNCF pattern research, user consultation, and adversarial review.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| KagentiPlatform CRD scope | **Cluster-scoped** | Aligns with OpenShift convention, DSC pattern, singleton semantics |
| Observability (MLflow) | **Deferred to AgentRuntime CRD** | MLflow integration handled by AgentRuntime controller in a later phase; no separate Observability CRD |
| Auth model | **Generic OIDC spec** | `spec.auth.oidc` with issuerURL/clientID; Keycloak as one provider option |
| Repo location | **Monorepo (kagenti/kagenti)** | New `platform-operator/` directory with separate `go.mod` and dedicated CI workflow |
| Tier 3 Quickstart | **Script + Make + existing env configs** | No quickstart operator; follows Istio/Knative/Dapr CNCF pattern |
| Chart migration | **Incremental** | Keep `kagenti-deps` working; migrate components to operator over time |
| Scaffolding | **Kubebuilder** | Standard CNCF tooling |

### Architecture Summary

```
Tier 3: deploy.sh + make dev-setup     Tier 2: ODH/RHOAI       Standalone
(dev/PoC, env-file driven)             (production)             (advanced user)
         │                                  │                       │
         │  helm install kagenti-deps       │  DSCi + OLM deps      │  manual / GitOps
         │  kubectl apply KagentiPlatform   │  creates CR            │  kubectl apply CR
         ▼                                  ▼                       ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │         Tier 1: Kagenti Platform Operator (Kubebuilder)          │
    │         Reconciles: KagentiPlatform                                │
    │         Validates infrastructure, deploys Kagenti components      │
    └──────────────────────────────────────────────────────────────────┘
```

---

## Phase A: CRD + Platform Controller (6 weeks)

*Extended from 4 to 6 weeks per reviewer feedback: the existing operator detection logic, OpenShift version gating, and platformOperator/kagentiOperator naming require careful modeling.*

### A.1 Scaffold the Platform Operator

**Directory**: `platform-operator/` (new, in monorepo root, own `go.mod`)

```bash
cd platform-operator/
kubebuilder init --domain kagenti.dev --repo github.com/kagenti/kagenti/platform-operator
kubebuilder create api --group "" --version v1alpha1 --kind KagentiPlatform --resource --controller
```

**CI**: Dedicated GitHub Actions workflow `.github/workflows/platform-operator.yaml` (separate from existing Python CI). Triggered on `platform-operator/**` path changes. Runs: Go lint, Go test, envtest, container build, push to `ghcr.io/kagenti/kagenti-platform-operator`.

### A.2 KagentiPlatform CRD Schema

Cluster-scoped, singleton. Changes from V9.1:
- **Generic OIDC** replaces Keycloak-only auth spec
- **managementState tri-state** on all components: `Managed | Removed | Unmanaged`
- **Infrastructure requirement tri-state**: `Required | Optional | Ignored`
- **Per-component status conditions** (reviewer fix #3)

```go
// api/v1alpha1/kagentiplatform_types.go
type KagentiPlatformSpec struct {
    // Core Components
    AgentOperator   ComponentSpec       `json:"agentOperator"`
    Webhook         ComponentSpec       `json:"webhook"`
    UI              UISpec              `json:"ui"`
    MCPGateway      ComponentSpec       `json:"mcpGateway"`
    AgentNamespaces []AgentNamespace    `json:"agentNamespaces,omitempty"`

    // Auth (generic OIDC)
    Auth            AuthSpec            `json:"auth"`

    // Infrastructure References (validate-only, read-only RBAC)
    Infrastructure  InfrastructureSpec  `json:"infrastructure"`

    // Global
    Domain          string              `json:"domain,omitempty"`
    DeletionPolicy  DeletionPolicy      `json:"deletionPolicy,omitempty"`
    ImageOverrides  ImageOverridesSpec  `json:"imageOverrides,omitempty"`
}

type AuthSpec struct {
    ManagementState ManagementState `json:"managementState"`
    OIDC OIDCSpec                   `json:"oidc"`
}

type OIDCSpec struct {
    IssuerURL            string            `json:"issuerURL"`
    ClientID             string            `json:"clientID,omitempty"`
    CredentialsSecretRef SecretRef         `json:"credentialsSecretRef,omitempty"`
    RequiredScopes       []string          `json:"requiredScopes,omitempty"`
    RequiredClaims       map[string]string `json:"requiredClaims,omitempty"`
    // Keycloak-specific (optional, only when using bundled Keycloak)
    Keycloak *KeycloakSpec                 `json:"keycloak,omitempty"`
}
```

### A.3 Per-Component Status Conditions (Reviewer Fix #3)

Users must be able to distinguish "reconciling" from "stuck on webhook for 20 minutes":

```go
type KagentiPlatformStatus struct {
    Phase              PlatformPhase      `json:"phase"` // Installing | Ready | Degraded | Blocked | Error
    ObservedGeneration int64              `json:"observedGeneration"`
    Environment        EnvironmentStatus  `json:"environment,omitempty"`

    // Per-component status (reviewer fix #3)
    Components struct {
        AgentOperator ComponentStatus `json:"agentOperator"`
        Webhook       ComponentStatus `json:"webhook"`
        UI            ComponentStatus `json:"ui"`
        Auth          ComponentStatus `json:"auth"`
        MCPGateway    ComponentStatus `json:"mcpGateway,omitempty"`
    } `json:"components"`

    // Per-infrastructure-dep status
    Infrastructure struct {
        CertManager InfraComponentStatus `json:"certManager"`
        Istio       InfraComponentStatus `json:"istio"`
        SPIRE       InfraComponentStatus `json:"spire"`
        Tekton      InfraComponentStatus `json:"tekton"`
        Shipwright  InfraComponentStatus `json:"shipwright"`
        GatewayAPI  InfraComponentStatus `json:"gatewayApi"`
    } `json:"infrastructure"`

    // Standard conditions array
    Conditions []metav1.Condition `json:"conditions,omitempty"`
    // Conditions: InfrastructureReady, AgentOperatorReady, WebhookReady,
    //             UIReady, AuthReady, Available, FullyOperational
}

type ComponentStatus struct {
    Status  string `json:"status"`            // Ready | Installing | Error | Removed
    Message string `json:"message,omitempty"` // Human-readable detail on error
    LastTransitionTime metav1.Time `json:"lastTransitionTime,omitempty"`
}
```

### A.4 Component Interface

From V9.1 Section 6.1, in `platform-operator/internal/components/`:

```go
type Component interface {
    Name() string
    Enabled(spec *v1alpha1.KagentiPlatformSpec) bool
    Install(ctx context.Context, p *v1alpha1.KagentiPlatform, env *Environment) error
    IsReady(ctx context.Context) (bool, string, error)
    Uninstall(ctx context.Context) error
}
```

Phase A components:
- `AgentOperatorComponent` — deploys kagenti-operator via Helm (reuses existing `charts/kagenti` dependency on `kagenti-operator-chart`)
- `WebhookComponent` — deploys kagenti-webhook
- `UIComponent` — deploys frontend + backend Deployments, Services, Ingress/HTTPRoutes
- `AuthComponent` — Keycloak realm init or generic OIDC client setup

### A.5 RBAC — Honest Accounting (Reviewer Fix #2)

The Platform Operator deploys components across namespaces. Here is the actual RBAC surface:

```yaml
# ClusterRole: kagenti-platform-operator
rules:
  # --- Infrastructure validation (READ-ONLY) ---
  - apiGroups: ["apiextensions.k8s.io"]
    resources: ["customresourcedefinitions"]
    verbs: ["get", "list", "watch"]

  # --- Own CRDs ---
  - apiGroups: ["kagenti.dev"]
    resources: ["kagentiplatforms", "kagentiplatforms/status", "kagentiplatforms/finalizers"]
    verbs: ["get", "list", "watch", "update", "patch"]

  # --- Kagenti components (multi-namespace: kagenti-system + agent namespaces) ---
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "configmaps", "secrets", "serviceaccounts"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

  # --- Networking ---
  - apiGroups: ["gateway.networking.k8s.io"]
    resources: ["httproutes", "referencegrants"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

  # --- Namespace management (agent namespaces, labels, mesh enrollment) ---
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list", "create", "update", "patch"]

  # --- RBAC for agent namespaces (ServiceAccount, Role, RoleBinding) ---
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

  # --- Helm release management (operator installs sub-charts) ---
  # The operator uses helm-sdk to install kagenti-operator chart.
  # This requires access to Helm release Secrets in target namespaces.

  # --- OpenShift-specific (RHOAI bundle only, not standalone K8s bundle) ---
  # - apiGroups: ["config.openshift.io"]
  #   resources: ["clusterversions", "dnses"]
  #   verbs: ["get", "list"]
```

**This is NOT cluster-admin.** Key differences from cluster-admin:
- No `escalate` or `bind` verbs
- No CRD creation (CRDs ship in the OLM bundle, not created at runtime)
- No OLM management (no Subscription/CSV/InstallPlan CRUD)
- No mutation of third-party CRs (Istio, SPIRE, Keycloak resources are read-only)
- Namespace operations limited to agent namespaces declared in the CR spec

### A.6 Migration Fence (Reviewer Fix #4)

Prevent collision between Ansible-managed and operator-managed installs:

**Operator side**: On first reconciliation, check for Helm release Secrets labeled `app.kubernetes.io/managed-by: Helm` with release names `kagenti` or `kagenti-deps` in `kagenti-system`. If found and NOT labeled `app.kubernetes.io/managed-by: kagenti-platform-operator`:
- Set `status.phase = Blocked`
- Set condition: `type: MigrationRequired, status: True, message: "Existing Helm releases found managed by Ansible/manual install. Run 'make adopt' or delete releases before operator can manage."`

**Ansible side**: In `00_preflight.yaml`, check if `KagentiPlatform` CRD exists:
```yaml
- name: Check if KagentiPlatform CRD exists (operator-managed cluster)
  command: kubectl get crd kagentiplatforms.kagenti.dev
  register: platform_crd_check
  failed_when: false
  changed_when: false

- name: Fail if operator-managed cluster detected
  fail:
    msg: |
      KagentiPlatform CRD detected — this cluster is managed by the Platform Operator.
      Use 'kubectl edit kagentiplatform kagenti' instead of the Ansible installer.
      To force Ansible install anyway, set FORCE_ANSIBLE=true.
  when: platform_crd_check.rc == 0 and not (force_ansible | default(false))
```

**Adoption path**: `make adopt` runs a script that relabels existing Helm releases with `app.kubernetes.io/managed-by: kagenti-platform-operator` and creates the KagentiPlatform CR from current Helm values (SSA with ForceOwnership, per V9.1 Section 10.1).

### A.7 Tests

- `envtest` suite: CRD registration, Platform Controller reconciliation, infrastructure validation
- Unit tests: Component interface, environment detection, migration fence logic
- Integration test (Kind): End-to-end install via `make dev-setup`, verify `status.phase == Ready`

---

## Phase B: Chart Migration Tracking + MLflow Prep (2 weeks)

### B.1 Chart Migration Tracking

No rename of `kagenti-deps`. Instead, track which components have migrated:

**In `charts/kagenti-deps/values.yaml`**, add comments:
```yaml
# MIGRATION STATUS: This chart is being incrementally migrated to the Platform Operator.
# Components marked [MIGRATED] are now managed by KagentiPlatform CR.
# Components marked [PREREQ] remain in this chart (infrastructure prerequisites).
```

As components move to operator management, their templates are removed from `kagenti-deps` and the values default to `enabled: false`.

### B.2 MLflow — Stays in `kagenti-deps` Chart (Deferred to AgentRuntime)

MLflow remains deployed via the `kagenti-deps` Helm chart for now. In a later phase, MLflow integration (experiment tracking, model registry) will be managed by the **AgentRuntime CRD and controller** in the kagenti-operator, since observability is a per-runtime concern — not a platform-level singleton. This avoids introducing a separate KagentiObservability CRD.

**Phoenix is out of scope** — removed from all deployment profiles.

### B.3 OTel Collector — Stays in `kagenti-deps` Chart

The OTel Collector remains an infrastructure prerequisite deployed by `kagenti-deps`. It is not managed by the Platform Operator since it serves as shared infrastructure (similar to cert-manager or Istio).

---

## Phase C: Deploy Script + Env Configs (3 weeks, parallel with B)

### C.1 Reuse Existing Env Configs (Reviewer Fix #1)

**No new `deployments/profiles/` directory.** The existing `deployments/envs/` files already serve as profiles. Instead, extend each env file with a `platform:` section for the KagentiPlatform CR spec:

**Existing files, extended**:
- `deployments/envs/dev_values.yaml` — add `platform:` section with full-dev CR spec
- `deployments/envs/dev_values_minimal.yaml` — add `platform:` section with minimal CR spec
- `deployments/envs/dev_values_minimal_auth.yaml` — add `platform:` section
- `deployments/envs/ocp_values.yaml` — add `platform:` section for OpenShift
- `deployments/envs/ocp_minimal_values.yaml` — add `platform:` section

Example addition to `dev_values_minimal.yaml`:
```yaml
# ... existing Helm values above (unchanged) ...

####################################################################
# KagentiPlatform CR spec (used by deploy.sh, ignored by Ansible)
####################################################################
platform:
  apiVersion: kagenti.dev/v1alpha1
  kind: KagentiPlatform
  metadata:
    name: kagenti
  spec:
    agentOperator: { managementState: Managed }
    webhook: { managementState: Removed }
    ui: { managementState: Managed }
    auth: { managementState: Removed }
    infrastructure:
      istio: { requirement: Ignored }
      spire: { requirement: Ignored }
      certManager: { requirement: Required }
      gatewayApi: { requirement: Required }
      tekton: { requirement: Required }
      shipwright: { requirement: Ignored }
    domain: localtest.me
```

The Ansible installer ignores the `platform:` key (it's not referenced in any task). The `deploy.sh` script reads it with `yq` to generate the KagentiPlatform CR.

### C.2 deploy.sh — Step-by-Step Mapping from Ansible (Reviewer Fix #7)

The 29 Ansible steps map to three layers. Here is the explicit decomposition:

#### Steps that move to `deploy.sh` (script, thin orchestration):

| # | Ansible Step | deploy.sh Equivalent |
|---|-------------|---------------------|
| 1 | `01_setup_vars.yaml` — load values, merge secrets | `yq` to parse env file, extract prereq values and platform CR |
| 2 | `00_preflight.yaml` — check cluster, tools | `kubectl cluster-info`, `helm version`, migration fence check |
| 3 | `02_setup_cluster.yaml` — create Kind cluster | `kind create cluster --config` (with `--skip-cluster` flag) |
| 4 | Image preloading (async) | `kind load docker-image` (parallel, background) |
| 5 | Install Tekton (kubectl apply) | `helm install kagenti-deps` handles this |
| 6-9 | Install Istio (base, istiod, cni, ztunnel) | `helm install kagenti-deps` handles this |
| 10 | Install cert-manager | `helm install kagenti-deps` handles this |
| 11 | Install Kiali + Prometheus | `helm install kagenti-deps` handles this |
| 12 | Install Shipwright | `04_install_shipwright.yaml` → `helm install kagenti-deps` handles this |
| 13-14 | Install SPIRE (crds + server) | `helm install kagenti-deps` handles this |
| 15 | Install Gateway API | `helm install kagenti-deps` handles this |
| 16 | Install kagenti-deps chart | `helm install kagenti-deps -f <prereq-values>` |
| 17 | Wait for CRDs | `kubectl wait --for=condition=Established crd/...` |
| 18 | Install Platform Operator | `helm install kagenti-platform-operator` |
| 19 | Apply KagentiPlatform CR | `kubectl apply -f <generated-cr.yaml>` |
| 20 | Wait for Ready | `kubectl wait --for=jsonpath='{.status.phase}'=Ready kagentiplatform/kagenti` |
| 21 | `03_setup_kind_registry_dns.yaml` | Kept in script (Kind-specific CoreDNS patch) |
| 22 | Print URLs | `show-services.sh` |

#### Steps that move to the Platform Operator (controller reconciliation):

| Ansible Step | Operator Component |
|-------------|-------------------|
| Install kagenti chart (Helm) | `AgentOperatorComponent` + `UIComponent` + `AuthComponent` + `WebhookComponent` |
| SPIFFE IdP setup job (RBAC, Job, wait) | `AuthComponent` (when SPIRE + Keycloak both enabled) |
| Agent namespace creation + labeling | `AgentNamespaceComponent` |
| OAuth secret jobs (ui, agent, api, mlflow) | `AuthComponent` |
| UI routes job | `UIComponent` |

#### Steps that stay in `kagenti-deps` Helm chart (infrastructure prerequisites):

| Ansible Step | Chart Template |
|-------------|---------------|
| Keycloak (operator, instance, realm) | `keycloak-*.yaml` |
| OTel Collector | `otel-collector.yaml` |
| MLflow | `mlflow.yaml` (moves to AgentRuntime controller in a later phase) |
| MCP Inspector | `mcp-inspector.yaml` |
| Container Registry | `container-registry.yaml` |
| Metrics Server | `metrics-server.yaml` |
| Ingress Gateway | `ingress-gateway.yaml` |

#### Steps that are DROPPED (OpenShift-specific, handled differently):

| Ansible Step | Disposition |
|-------------|------------|
| OLM operator detection (cert-manager, SPIRE, Builds) | Platform Operator infra validator replaces this |
| OpenShift version detection + ZTWIM fallback | Platform Operator `environment.Detect()` |
| TektonConfig SCC patching | Stays in kagenti-operator's TektonConfigReconciler |
| Shared Trust CA workaround (RHOAI 2.x legacy) | Dropped — RHOAI 3.x only |
| Wait for OpenShift Builds operator | OLM dependency in RHOAI CSV bundle |

### C.3 Makefile Targets

```makefile
dev-setup:              ## Create Kind cluster + full install (dev env)
	./deploy.sh dev

dev-setup-minimal:      ## Create Kind cluster + minimal install (no auth/mesh)
	./deploy.sh minimal

dev-teardown:           ## Destroy Kind cluster
	kind delete cluster --name kagenti

dev-reinstall:          ## Reinstall on existing cluster (skip cluster create)
	./deploy.sh --skip-cluster dev

adopt:                  ## Adopt existing Ansible-managed install into operator
	./scripts/adopt-helm-releases.sh
```

### C.4 Backward Compatibility

Both paths work during migration:
- **New**: `make dev-setup` (deploy.sh + Platform Operator)
- **Old**: `deployments/ansible/run-install.sh --env dev` (Ansible, unchanged)

Migration fence (A.6) prevents accidental collision.

---

## Phase D: ODH/RHOAI Component Handler (2 weeks, parallel with B/C)

Per V9.1 Section 3.4.2 — ~200-line Go adapter for `opendatahub-io/opendatahub-operator`. Dual CSV bundles (standalone soft deps, RHOAI hard deps) from same binary.

---

## Phase E: Productization (2 weeks)

- Konflux pipeline for Platform Operator image
- OLM bundle generation (dual: standalone + RHOAI)
- Red Hat operator certification
- Deprecation notice on Ansible installer

---

## Verification Plan

### Phase A Verification
```bash
# 1. Go tests (unit + envtest)
cd platform-operator && make test

# 2. Integration: install on Kind
make dev-setup
kubectl get kagentiplatform kagenti -o jsonpath='{.status.phase}'
# Expected: Ready

# 3. Per-component status visible
kubectl get kagentiplatform kagenti -o jsonpath='{.status.components}'
# Expected: agentOperator.status=Ready, ui.status=Ready, etc.

# 4. Infrastructure validation
kubectl delete crd certificates.cert-manager.io
# Wait for reconciliation...
kubectl get kagentiplatform kagenti -o jsonpath='{.status.phase}'
# Expected: Blocked
kubectl get kagentiplatform kagenti -o jsonpath='{.status.conditions}'
# Expected: InfrastructureReady=False

# 5. Migration fence
# On a cluster with existing Ansible install:
kubectl apply -f platform-operator/config/crd/bases/
kubectl apply -f example-cr.yaml
kubectl get kagentiplatform kagenti -o jsonpath='{.status.phase}'
# Expected: Blocked (MigrationRequired condition)
```

### Phase C Verification
```bash
# Env-based install
./deploy.sh minimal
kubectl get kagentiplatform kagenti -o yaml
# Verify: auth.managementState=Removed, infrastructure.istio.requirement=Ignored

# Ansible still works
deployments/ansible/run-install.sh --env dev
```

---

## Critical Files

| Phase | File | Action |
|-------|------|--------|
| A | `platform-operator/` (new) | Kubebuilder scaffold, own `go.mod` |
| A | `platform-operator/api/v1alpha1/kagentiplatform_types.go` | CRD with per-component status |
| A | `platform-operator/internal/controller/platform_controller.go` | Main reconciler |
| A | `platform-operator/internal/infrastructure/validator.go` | Read-only infra checks |
| A | `platform-operator/internal/components/*.go` | Component implementations |
| A | `platform-operator/internal/migration/fence.go` | Helm release detection |
| A | `.github/workflows/platform-operator.yaml` (new) | Dedicated Go CI |
| A | `Makefile` | Add platform-operator + dev-setup targets |
| A | `deployments/ansible/roles/kagenti_installer/tasks/00_preflight.yaml` | Add CRD fence check |
| B | `charts/kagenti-deps/values.yaml` | Migration tracking comments, remove Phoenix templates |
| C | `deploy.sh` (new) | Replaces Ansible entrypoint for new installs |
| C | `deployments/envs/dev_values.yaml` | Add `platform:` section |
| C | `deployments/envs/dev_values_minimal.yaml` | Add `platform:` section |
| C | `deployments/envs/ocp_values.yaml` | Add `platform:` section |
| D | Upstream PR to opendatahub-io | ODH component handler |

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Ansible ↔ operator collision during migration | Migration fence: operator blocks if unowned Helm releases exist; Ansible blocks if KagentiPlatform CRD exists (A.6) |
| Go module in Python monorepo complicates CI | Separate `go.mod`, dedicated `.github/workflows/platform-operator.yaml`, path-filtered triggers |
| RBAC broader than "read-only validator" suggests | Honest RBAC manifest in plan (A.5). No escalate/bind. Dual CSV for OpenShift-specific rules. |
| Users can't diagnose stuck installs | Per-component status conditions with LastTransitionTime and human-readable messages (A.3) |
| `deploy.sh` replicates Ansible complexity | Script is thin orchestrator (~200 lines). Complexity lives in kagenti-deps chart (prereqs) and Platform Operator (components). Explicit step mapping in C.2. |
| Phase A timeline (6 weeks) still tight | Scope Phase A to Kind + vanilla K8s only. OpenShift-specific logic (OLM detection, version gating) deferred to Phase D. |

## Timeline

| Phase | Duration | Deliverables | Dependencies |
|-------|----------|-------------|-------------|
| A: CRD + Platform Controller | 6 weeks | KagentiPlatform CRD, infra validator, 4 components, migration fence, envtest | None |
| B: Chart Migration + MLflow Prep | 2 weeks | Chart migration tracking, remove Phoenix, document MLflow→AgentRuntime path | Phase A |
| C: Deploy Script | 3 weeks | deploy.sh, Makefile targets, env file extensions | Phase A |
| D: ODH Component (Tier 2) | 2 weeks | ODH adapter, dual CSV bundles | Phase A |
| E: Productization | 2 weeks | Konflux pipeline, OLM bundle, certification | Phases A-D |

Phases B, C, D run in parallel. **Total: ~13 weeks.**
