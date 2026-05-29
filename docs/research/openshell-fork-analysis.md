# Kagenti OpenShell Fork: Architecture, Patches, and Upgrade Path

*Comprehensive analysis of how Kagenti maintains and extends the
NVIDIA/OpenShell fork, what custom patches exist, and the plan for
syncing with upstream v0.0.49+.*

---

## Fork Architecture

Kagenti maintains three repositories forked from the OpenShell ecosystem:

```mermaid
flowchart TB
    subgraph UPSTREAM["NVIDIA Upstream"]
        NOS["NVIDIA/OpenShell\n(gateway + supervisor + K8s driver)\nv0.0.49 (May 2026)"]
    end

    subgraph KAGENTI["Kagenti Fork"]
        KOS["kagenti/openshell\n(gateway + supervisor)\nmvp branch → v0.0.36-kagenti.8"]
        KDR["kagenti/openshell-driver-openshift\n(Go compute driver)\nmvp branch"]
        KCR["kagenti/openshell-credentials-keycloak\n(credentials driver)\nmain branch"]
    end

    NOS -->|"Sync Fork"| KOS
    KOS -->|"Unix socket"| KDR
    KOS -->|"Unix socket"| KCR

    style UPSTREAM fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style KAGENTI fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

### Branch Strategy

| Repo | Main Branch | Build Branch | Relationship |
|------|-------------|-------------|--------------|
| kagenti/openshell | `main` (synced with NVIDIA) | `mvp` (32 commits ahead) | `main` = upstream mirror, `mvp` = kagenti patches |
| kagenti/openshell-driver-openshift | `main` | `mvp` | Kagenti-specific, no upstream equivalent |
| kagenti/openshell-credentials-keycloak | `main` | `main` | Kagenti-specific, no upstream equivalent |

### How Builds Work

1. **Sync Fork**: GitHub "Sync Fork" button syncs `kagenti/openshell:main` with `NVIDIA/OpenShell:main`
2. **Rebase mvp**: Claude Code rebases the `mvp` branch onto the updated `main`
3. **Evaluate patches**: Check if kagenti-specific PRs on `mvp` are still needed (some may have been fixed upstream)
4. **Tag release**: Create `v0.0.XX-kagenti.N` tag from the rebased `mvp`
5. **Build images**: CI builds gateway + supervisor multi-arch images from the tagged commit

### Current Image Tags

| Component | Image | Tag | Source |
|-----------|-------|-----|--------|
| Gateway | `ghcr.io/kagenti/openshell/gateway` | `v0.0.36-kagenti.8` | mvp branch |
| Supervisor | `ghcr.io/kagenti/openshell/supervisor` | `v0.0.36-kagenti.8` | mvp branch |
| Compute Driver | `ghcr.io/kagenti/openshell-driver-openshift/compute-driver` | `mvp-a5f33f4` | mvp branch |
| Credentials Driver | `ghcr.io/kagenti/openshell-credentials-keycloak/credentials-driver` | `main-d7d8306` | main branch |

---

## Custom Patches on mvp Branch

These PRs were merged into the kagenti/openshell `mvp` branch and represent
our divergence from upstream:

### Gateway Patches

| PR | Title | Still needed? |
|----|-------|---------------|
| #1 | Gateway fork: `--compute-driver-socket` and `--credentials-driver-socket` flags with OIDC | **Yes** — upstream K8s driver is in-process Rust, ours is out-of-process Go via Unix socket |
| #2 | Multi-arch supervisor images (linux/amd64 + linux/arm64) | **Maybe not** — upstream v0.0.49 ships multi-arch binaries |
| #3 | Remove NVIDIA self-hosted CI runners | **Yes** — CI infrastructure difference |
| #4 | Custom Kagenti CI workflows for gateway/supervisor publishing | **Yes** — our GHCR registry |
| #5 | OpenShell CLI release workflow | **Maybe not** — depends on whether we ship the CLI |
| #6 | Sandbox fixes: SSH permissions, `/tmp` writability | **Check** — may be fixed upstream |
| #7 | Inference routing on Kind (sandbox-system route) | **Check** — upstream may handle differently |

### Compute Driver Patches (openshell-driver-openshift)

| PR | Title | Still needed? |
|----|-------|---------------|
| #1 | Namespace flags + tenant labels | **Yes** — multi-tenancy, not in upstream K8s driver |
| #2 | Scoped RBAC (namespace Role, not cluster-admin) | **Yes** — security, not in upstream |
| #3 | mTLS + inference routing | **Yes** — Kagenti-specific wiring |
| #4 | Sandbox image pull policy configuration | **Yes** — Kind/HyperShift compatibility |

### Credentials Driver (openshell-credentials-keycloak)

Entirely Kagenti-specific — exchanges OIDC tokens via Keycloak for sandbox
authentication. No upstream equivalent exists.

---

## Known Issues in Current Fork

### Issue #1647: OPA Wildcard Matching

**Symptom**: `*.svc.cluster.local` in policy doesn't match actual hostnames.

**Root cause**: OPA rego uses `glob.match()` with `.` as delimiter. Single `*`
matches one DNS label only. `*.svc.cluster.local` matches `foo.svc.cluster.local`
but NOT `litellm-model-proxy.team1.svc.cluster.local` (two labels before `.svc`).

**Status**: Upstream v0.0.49 rego uses `**` for cross-label matching. Our v0.0.36
may not have this. The rego file itself supports `**` — the issue is that our
**policy-data.yaml files** use `*` instead of `**`.

**Fix in PR #1689**: Replaced wildcard policies with explicit service endpoints
(e.g., `litellm-model-proxy.team1.svc.cluster.local:4000`).

### Issue #1669: port vs ports Normalization

**Symptom**: Policy submitted with `ports: [8335]` (plural) reads back as
`port: 8335` (singular) from `openshell sandbox get --policy-only`.

**Root cause**: The proto defines both `port` (field 2, uint32, backwards compat)
and `ports` (field 9, repeated uint32). The gateway's response serialization
normalizes `ports` back to `port` — a **gateway serialization bug**.

**Status**: The rego evaluator correctly uses `endpoint.ports[_]` (plural).
The normalization from `port` → `ports` happens on input. But the **inverse
normalization on output** strips the list back to scalar. This may be fixed in
upstream v0.0.49 but needs verification after fork sync.

### Issue: glibc Compatibility

**Symptom**: Supervised agents crash with `GLIBC_2.38/2.39 not found`.

**Root cause**: Supervisor binary built against Ubuntu 24.04 (glibc 2.39),
agent Dockerfiles used `python:3.12-slim` (Debian bookworm, glibc 2.36).

**Fixed in PR #1689**: Upgraded to `python:3.13-slim` (Debian trixie, glibc 2.40).

---

## Upstream K8s Driver vs Our Compute Driver

The colleague's question: "do we still need openshell-driver-openshift now
that the kubernetes driver is in openshell upstream?"

| Feature | Upstream K8s Driver | kagenti/openshell-driver-openshift |
|---------|--------------------|------------------------------------|
| Language | Rust (in-process with gateway) | Go (out-of-process via Unix socket) |
| CRD | `agents.x-k8s.io/v1alpha1` Sandbox | Same |
| Multi-tenancy | Single namespace | Per-tenant namespace isolation |
| RBAC | Cluster-level | Namespace-scoped Roles |
| Tenant labels | None | `openshell.ai/tenant`, `kagenti.io/team` |
| PVC persistence | Workspace PVC per sandbox | Same |
| GPU support | Yes (preflighting) | Not tested |
| Image pull policy | Default | Configurable (IfNotPresent for Kind) |
| dtach injection | Unknown | Yes (session persistence) |
| OpenShift SCCs | No | Yes (anyuid, privileged for supervisor) |

**Verdict**: We still need our driver for **multi-tenancy** (namespace isolation,
tenant labels, scoped RBAC) and **OpenShift support** (SCCs). The upstream
driver could replace ours if we upstream the multi-tenancy features.

---

## Upgrade Plan

### Immediate (v0.6.0 stabilization window)

Per colleague's request, **hold the fork sync** until v0.6.0 RC is stable.
Current work continues on the existing `v0.0.36-kagenti.8` images.

### Step 1: Sync Fork (after v0.6.0)

```bash
# On kagenti/openshell — Sync Fork button on GitHub
# Then rebase mvp:
git fetch origin main
git checkout mvp
git rebase origin/main
# Resolve conflicts in kagenti-specific patches
```

### Step 2: Evaluate Patches

For each PR on `mvp`, check if upstream v0.0.49 includes the fix:
- SSH permissions → likely fixed
- Multi-arch builds → upstream ships multi-arch now
- Socket flags → still needed (our Go driver is out-of-process)
- CI workflows → still needed (our GHCR)

### Step 3: Test

1. Build new images from rebased `mvp`
2. Deploy to Kind with updated Helm chart tags
3. Run T7 teleport tests (12 tests)
4. Test policy normalization (#1669)
5. Test wildcard matching (#1647)
6. Verify glibc compatibility

### Step 4: Evaluate Compute Driver Migration

If upstream K8s driver gains multi-tenancy features, we can deprecate
`openshell-driver-openshift`. Key upstream PRs to track:
- Namespace isolation per tenant
- Scoped RBAC (not cluster-admin)
- OpenShift SCC support

---

## Upgrade Plan: Safe Branch Strategy

### Principle: Never Touch mvp

The `mvp` branch is the production build target. All upgrade work happens
on parallel branches. Old branches are preserved for rollback.

```mermaid
flowchart TB
    subgraph NVIDIA["NVIDIA Upstream"]
        NM["main (v0.0.49)"]
    end

    subgraph KAGENTI["kagenti/openshell"]
        KM["main"] -->|"Sync Fork"| NM
        MVP["mvp\n(v0.0.36-kagenti.8)\nUNTOUCHED"]
        NEW["mvp-2026-05-29\n(branched from synced main)"]
        KM --> NEW
        NEW -->|"cherry-pick\nkagenti patches"| NEW
        NEW -->|"after testing"| MVP2["mvp\n(updated)"]
        MVP -->|"archive"| ARCHIVE["mvp-v0.0.36-archive"]
    end

    style MVP fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style NEW fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style ARCHIVE fill:#555,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

### Branch Naming

| Repo | Current Build Branch | New Test Branch | Archive |
|------|---------------------|-----------------|---------|
| kagenti/openshell | `mvp` | `mvp-2026-05-29` | `mvp-v0.0.36-archive` |
| kagenti/openshell-driver-openshift | `mvp` | `mvp-2026-05-29` | `mvp-v0.0.36-archive` |
| kagenti/openshell-credentials-keycloak | `main` | `main-2026-05-29` | (no change needed) |

### Step-by-Step Procedure

**Step 1: Sync kagenti/openshell main with NVIDIA upstream**
- Use GitHub "Sync Fork" button on kagenti/openshell
- This updates `main` to NVIDIA v0.0.49+
- `mvp` is NOT affected

**Step 2: Create new branch from synced main**
```bash
cd /tmp && git clone git@github.com:kagenti/openshell.git openshell-upgrade
cd openshell-upgrade
git checkout -b mvp-2026-05-29 origin/main
```

**Step 3: Cherry-pick kagenti patches (9 essential patches)**

All patches verified as still needed (no upstream equivalent in v0.0.49):

| # | Commit | Description | Category |
|---|--------|-------------|----------|
| 1 | `9f830673` | `--compute-driver-socket` flag (External driver) | Gateway core |
| 2 | `136441fe` | `--credentials-driver-socket` flag + gRPC service | Gateway core |
| 3 | `906f3995` | OIDC/Keycloak JWT auth with RBAC | Gateway auth |
| 4 | `0f56d6e4` | `credentials_driver.proto` contract | Proto |
| 5 | `124128bd` | Stop SSH from overwriting `/tmp` to 0700 | Sandbox fix |
| 6 | `9a02d72e` | Ensure read_write dirs writable (mode 1777) | Sandbox fix |
| 7 | `6aef2e86` | Pass inference env vars through SSH sessions | Inference routing |
| 8 | `0dea760e` | GHCR gateway image publish workflow | CI |
| 9 | `abc24202` | Multi-arch supervisor build (amd64 + arm64) | CI |

Patches NOT cherry-picked (evaluate if upstream fixed):
- `9468139f` (portable `MetadataExt::uid()`) — minor, test if upstream compiles
- macOS CLI build fixes — platform-specific, test separately

```bash
# Cherry-pick in dependency order
git cherry-pick 0f56d6e4   # proto first
git cherry-pick 9f830673   # compute socket
git cherry-pick 136441fe   # credentials socket
git cherry-pick 906f3995   # OIDC auth
git cherry-pick 124128bd   # /tmp fix
git cherry-pick 9a02d72e   # dir permissions
git cherry-pick 6aef2e86   # inference routing
git cherry-pick 0dea760e   # CI gateway
git cherry-pick abc24202   # CI supervisor
```

**Step 4: Push test branch (not mvp)**
```bash
git push origin mvp-2026-05-29
```

**Step 5: Build test images from new branch**
- Tag: `v0.0.49-kagenti.1-rc1`
- Build gateway + supervisor images
- Do NOT push to `:latest` tag

**Step 6: Test on Kind**
```bash
# Update kagenti Helm chart to use new images
# In a worktree or branch of kagenti/kagenti:
# charts/openshell/values.yaml:
#   gateway.tag: v0.0.49-kagenti.1-rc1
#   supervisorImage.tag: v0.0.49-kagenti.1-rc1
```

Run full test suite:
- T0-T7 openshell tests
- T7 teleport (12 tests)
- Policy validation (#1647 wildcards)
- Port normalization (#1669)
- Agent connectivity (hermes + claude-code)

**Step 7: Create PR (mvp-2026-05-29 → mvp)**
- Only after all tests pass
- Only after v0.6.0 ships
- Include test results in PR description

**Step 8: Archive old mvp**
```bash
git branch mvp-v0.0.36-archive mvp  # preserve
git checkout mvp
git reset --hard mvp-2026-05-29     # update
git push --force-with-lease origin mvp
```

### Same process for driver repos

**openshell-driver-openshift:**
```bash
git checkout -b mvp-2026-05-29 origin/main
# Merge the 1 trailing commit from mvp
git cherry-pick <trailing-commit>
git push origin mvp-2026-05-29
```

**openshell-credentials-keycloak:**
- No branch needed — stays on `main`
- Test compatibility with v0.0.49 gateway

### Proto Compatibility

Verified: `compute_driver.proto` interface is stable between v0.0.36 and
v0.0.49. The ComputeDriver gRPC service (GetCapabilities, ValidateSandboxCreate,
GetSandbox, ListSandboxes) has no breaking changes. Existing drivers work
without modification.

### Rollback Plan

If the upgrade fails:
1. `mvp` branch was never touched (until Step 8)
2. Archive branch `mvp-v0.0.36-archive` preserves the exact state
3. Helm chart rollback: change image tags back to `v0.0.36-kagenti.8`
4. Driver repos: same rollback pattern

### Timeline

| When | Action |
|------|--------|
| **Now** | Create `mvp-2026-05-29` branches, cherry-pick patches |
| **Now** | Build RC images, test on Kind |
| **After v0.6.0** | Create PR from `mvp-2026-05-29` → `mvp` |
| **After PR review** | Merge, tag `v0.0.49-kagenti.1`, push images |
| **After CI green** | Update kagenti Helm chart to new tags |

---

## Hermes Agent Integration

### Current State (v0.15.1)

Hermes is an autonomous agent framework by Nous Research. v0.15.1 supports
`custom_providers` config but has a bug where the model name isn't forwarded
to the API request body (model= empty).

### Integration Path: ACP Adapter

Hermes has a built-in ACP adapter (`hermes acp`) that needs `[acp]` pip extras:

```dockerfile
RUN pip install --no-cache-dir \
    "hermes-agent[acp] @ https://github.com/NousResearch/hermes-agent/archive/refs/tags/v2026.5.29.tar.gz"
```

This exposes hermes as an ACP-compatible agent that the Kagenti backend can
communicate with via the ExecSandbox gRPC path or direct ACP WebSocket.

### LiteLLM Integration

Hermes needs to be configured to use our LiteLLM proxy for model routing.
The correct config for v0.15.1 uses `custom_providers`:

```yaml
model:
  default: claude-sonnet-4-20250514  # MUST use "default" not "name"
  provider: kagenti

custom_providers:
  - name: kagenti
    base_url: http://litellm-model-proxy.team1.svc:4000/v1
    api_key: <litellm-virtual-key>
    models:
      - claude-sonnet-4-20250514
      - vertex-claude-sonnet
      - llama-scout-17b
```

**Known bug** (NousResearch/hermes-agent#34500): `custom_providers` model
list not resolved by `provider_model_ids()`. Fixed with a patch in our
Dockerfile (`patch-custom-providers.py`). Config key must be `model.default`
(not `model.name`) — hermes reads `default` or `model` subkeys only.

---

## Vertex AI Integration

LiteLLM routes Claude models through Vertex AI using application default
credentials (ADC). Setup requires:

1. K8s Secret with ADC credentials mounted into LiteLLM pod
2. LiteLLM config with `vertex_ai/` model prefix and project/location

```yaml
# LiteLLM model config
- model_name: "claude-sonnet-4-20250514"
  litellm_params:
    model: "vertex_ai/claude-sonnet-4@20250514"
    vertex_project: "<project-id>"
    vertex_location: "us-east5"
    vertex_credentials: "/vertex-creds/credentials.json"
```

The sandbox agent only sees the LiteLLM virtual key — real Vertex AI
credentials never leave the LiteLLM pod.

---

*This document tracks the state of Kagenti's OpenShell fork as of May 2026.
Update after each fork sync or patch evaluation.*
