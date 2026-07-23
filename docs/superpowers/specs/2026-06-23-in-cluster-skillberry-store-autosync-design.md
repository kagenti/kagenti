---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Design: In-cluster skillberry-store with auto-enabled autosync

**Date:** 2026-06-23
**Status:** Approved (pending spec review)

## Problem

Today Rossoctl can sync skills from an **external** skillberry-store instance: the
operator runs the store somewhere reachable, allow-lists its address via
`--skill-registry-allowed-hosts`, and configures autosync by hand (UI/API). The
current workflow is:

```bash
scripts/kind/setup-rossoctl.sh --with-backend --with-ui --with-skills --with-builds \
  --build-images --skill-registry-allowed-hosts <IP-of-external-skillberry-store>
```

We want `--with-skills` to **deploy skillberry-store in-cluster as a pod** and
**enable autosync against it automatically**, with no external instance and no
manual allow-listing. The same capability must be reachable through any
deployment method (Helm, Ansible values overlays), not just the Kind script. The
store image version defaults to `0.2.0` and must be overridable. The
implementation should follow existing Rossoctl component patterns and avoid
reinventing mechanisms that already exist.

## Key insight

The autosync machinery already provides the wiring we need:

- A background loop in the backend (`run_skill_autosync_loop` →
  `sync_skills_once`) reads the `rossoctl-skill-autosync-config` ConfigMap in
  `rossoctl-system`, and if `enabled: "true"` with a `registry-url`, polls
  `{registry-url}/skills/` and reconciles skills into namespaces.
- The loop is started only when `featureFlags.externalSkills` is on — which
  `--with-skills` already enables.
- **Crucially, the loop trusts the `registry-url` from the ConfigMap with no SSRF
  validation.** SSRF validation (`_validate_registry_url`) runs only on
  user-submitted URLs in the POST endpoint
  (`rossoctl/backend/app/routers/skills.py:155`, called at lines 189/220).
  `_fetch_registry_skills` (`rossoctl/backend/app/services/skill_autosync.py:82`)
  fetches the ConfigMap URL directly.

Therefore the entire feature is achievable **declaratively in Helm with zero
backend code changes**:

1. Add `skillberry-store` as a chart component (Deployment + Service + PVC + HTTPRoute).
2. Seed the `rossoctl-skill-autosync-config` ConfigMap pointing at the in-cluster Service.
3. The existing backend loop picks it up and syncs.

No new feature flag is introduced; the feature is gated by the existing
`featureFlags.externalSkills` (behavior) and a new `components.skillberryStore.enabled`
toggle (resource deployment), both **off by default**.

## skillberry-store facts (from `github.com/skillberry-ai/skillberry-store`)

- **Image:** `ghcr.io/skillberry-ai/skillberry-store`, default tag `0.2.0`
  (matches `git_version.py` `__git_version__`). Publicly pullable.
- **Single container, two ports:** FastAPI/REST API on `8000`, web UI (Vite) on
  `8002`. Both started by the same process; UI controlled by `ENABLE_UI` (default
  true).
- **Storage:** filesystem-based (no embedded DB). Root dir `SBS_BASE_DIR`
  (default = system temp). All subdirectories live under it. We set
  `SBS_BASE_DIR=/data` and mount a PVC there.
- **Relevant API (port 8000):** `GET /skills/`, `GET /skills/{name}/export-anthropic`,
  `POST /skills/import-anthropic`. Health: `GET /health` (liveness),
  `GET /health/ready` (readiness).
- **Key env vars:** `SBS_HOST` (0.0.0.0), `SBS_PORT` (8000), `SBS_UI_PORT` (8002),
  `ENABLE_UI` (true), `SBS_BASE_DIR`.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Chart placement | `charts/rossoctl` (not `rossoctl-deps`) | Autosync bootstrap ConfigMap must live in the same chart as the consuming backend; skillberry-store is skills-feature-specific, not generic infra. Single chart, single flag path. |
| Auto-enable mechanism | Helm-rendered `rossoctl-skill-autosync-config` ConfigMap | Reuses the existing autosync-via-ConfigMap mechanism; no backend change. |
| SSRF allow-list | Not required for the built-in store | Autosync loop trusts the ConfigMap URL. `--skill-registry-allowed-hosts` remains for external registries. |
| Storage path | PVC at `/data` via `SBS_BASE_DIR=/data` | Cleaner and safer than mounting a PVC over `/tmp`. |
| UI exposure | API + browser UI | ClusterIP Service for `:8000` and `:8002`, plus an HTTPRoute for the UI (phoenix/mlflow pattern). |
| Version override | Chart value + env var in Kind script | Helm: `--set skillberryStore.image.tag=...`. Kind: `SKILLBERRY_STORE_TAG` / `SKILLBERRY_STORE_IMAGE` env vars (no new flag). |

*Alternative considered:* place the Deployment in `charts/rossoctl-deps` to match the
mlflow/keycloak backing-service precedent. Rejected: forces cross-chart URL
coordination (bootstrap ConfigMap in `rossoctl`, Deployment in `rossoctl-deps`) for
no real benefit.

## Changes

### 1. `charts/rossoctl/values.yaml`

Add the component toggle and config block (defaults off):

```yaml
components:
  skillberryStore:
    enabled: false

skillberryStore:
  image:
    repository: ghcr.io/skillberry-ai/skillberry-store
    tag: "0.2.0"            # override via --set or values overlay
    pullPolicy: IfNotPresent
  imagePullSecrets: []       # public image; empty default
  apiPort: 8000
  uiPort: 8002
  baseDir: /data             # SBS_BASE_DIR; PVC mount point
  persistence:
    enabled: true
    size: 5Gi
    storageClassName: ""     # "" = cluster default
    accessMode: ReadWriteOnce
  autosync:
    enabled: true            # seed rossoctl-skill-autosync-config when store deployed
    syncInterval: 30
    allowedTags: ""          # optional tag filter
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: "2"
      memory: 2Gi
```

### 2. `charts/rossoctl/templates/skillberry-store.yaml`

Gated by `{{- if .Values.components.skillberryStore.enabled }}`. Contains:

- **Deployment** — single container with ports 8000 (`api`) and 8002 (`ui`).
  Env: `SBS_BASE_DIR=/data`, `SBS_HOST=0.0.0.0`, `SBS_PORT=8000`,
  `SBS_UI_PORT=8002`, `ENABLE_UI=true`. PVC volume mounted at `/data`.
  Probes: liveness `GET /health` on 8000, readiness `GET /health/ready` on 8000.
  `imagePullSecrets`, `resources`, labels/selectors per `_helpers.tpl` conventions.
- **Service** (ClusterIP) — exposes `8000` (`api`) and `8002` (`ui`).
- **PersistentVolumeClaim** — `size`, `accessMode`, `storageClassName` from values
  (rendered only when `persistence.enabled`).
- **HTTPRoute** — routes the UI (`:8002`) following the phoenix/mlflow pattern, so
  the store UI is browsable at `http://skillberry-store.<domainName>:8080`.

### 3. `charts/rossoctl/templates/skillberry-autosync-configmap.yaml`

Gated by `{{- if and .Values.components.skillberryStore.enabled .Values.skillberryStore.autosync.enabled }}`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rossoctl-skill-autosync-config   # name the backend loop already reads
  namespace: {{ .Release.Namespace }}
data:
  enabled: "true"
  registry-type: "skillberry"
  registry-url: "http://skillberry-store.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.skillberryStore.apiPort }}"
  sync-interval: "{{ .Values.skillberryStore.autosync.syncInterval }}"
  allowed-tags: "{{ .Values.skillberryStore.autosync.allowedTags }}"
```

The backend writes status keys (`last-synced-at`, `skill-count`) into this same
ConfigMap. Helm's 3-way merge preserves keys it never set, so backend status
survives `helm upgrade`.

### 4. `scripts/kind/setup-rossoctl.sh`

`--with-skills` already enables `featureFlags.skills` + `featureFlags.externalSkills`
and auto-enables UI+backend. Add to `ROSSOCTL_FLAGS` when `WITH_SKILLS`:

```bash
ROSSOCTL_FLAGS+=(--set components.skillberryStore.enabled=true)
# Optional image override (no new flag):
[[ -n "${SKILLBERRY_STORE_IMAGE:-}" ]] && ROSSOCTL_FLAGS+=(--set "skillberryStore.image.repository=${SKILLBERRY_STORE_IMAGE}")
[[ -n "${SKILLBERRY_STORE_TAG:-}" ]]   && ROSSOCTL_FLAGS+=(--set "skillberryStore.image.tag=${SKILLBERRY_STORE_TAG}")
```

`--skill-registry-allowed-hosts` is unchanged (still used for external registries;
the built-in store needs no allow-listing). Update `--help` text to note that
`--with-skills` now deploys skillberry-store and to document `SKILLBERRY_STORE_TAG`/
`SKILLBERRY_STORE_IMAGE`.

### 5. Other deployment methods

- **Helm directly:** `--set components.skillberryStore.enabled=true`
  (plus `featureFlags.skills=true,featureFlags.externalSkills=true`).
- **Ansible / env values overlay:** `components.skillberryStore.enabled: true`.
- **Version override everywhere:** `--set skillberryStore.image.tag=0.2.1` or set
  in a values file; default remains `0.2.0`.

### 6. Documentation

- `docs/demos/demo-generic-agent-skillberry.md`: add an "in-cluster store" path
  (deploy via `--with-skills`; autosync auto-on; no external instance and no
  `--skill-registry-allowed-hosts` needed). Keep the external-instance flow as the
  alternative.
- `docs/skills.md`: document the in-cluster store and that `--with-skills` now
  deploys it.
- `docs/components.md` (and chart values reference): document the new
  `skillberryStore` component and image override.

## Testing

- **Helm render tests:** assert the Deployment, Service, PVC, HTTPRoute, and
  autosync ConfigMap render only when `components.skillberryStore.enabled=true`,
  and that the ConfigMap carries `enabled: "true"`, `registry-type: "skillberry"`,
  and the correct in-cluster `registry-url`. Assert nothing renders when disabled.
- **Image override test:** `--set skillberryStore.image.tag=X` produces image
  `...skillberry-store:X`.
- **Kind installer E2E:** extend the flag-detection map in
  `rossoctl/tests/e2e/common/test_kind_installer.py` so `--with-skills` is verified
  to produce a `skillberry-store` Deployment in `rossoctl-system`.

## Known limitations

- **Pre-existing ConfigMap adoption:** on an existing cluster where a user already
  created `rossoctl-skill-autosync-config` by hand (via UI/API), a fresh Helm install
  of the component would conflict (Helm cannot adopt an unmanaged resource). This is
  acceptable for the primary flow (fresh `--with-skills` install) and documented.
- **UI re-enable on upgrade:** if a user disables autosync via the UI (which deletes
  the ConfigMap), a subsequent `helm upgrade` re-creates it (re-enabling). Acceptable
  given the "deploy with `--with-skills` ⇒ autosync on" contract.
- **Single replica:** PVC is `ReadWriteOnce`; skillberry-store runs as a single
  replica. Multi-replica HA is out of scope.

## Out of scope

- Backend code changes (the declarative ConfigMap approach needs none).
- HA / multi-replica skillberry-store.
- Seeding the store with initial skills (it starts empty; users import skills as today).
- A new dedicated `rossoctl_feature_flag_*` (the existing `externalSkills` flag gates behavior).
