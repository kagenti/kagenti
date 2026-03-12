# Composable Sandbox Security — Design

> **Status:** Partial (T0-T3 wired, T4 blocked)
> **Date:** 2026-03-01 (Session F)
> **PR:** #758 (feat/sandbox-agent)

Replaces the previous fixed 3-profile model (Default/Hardened/Restricted) with
a composable layer system. Agent names are self-documenting -- the suffix lists
active security layers.

---

## 1. Core Model

Security is **composable, not fixed**. Each security layer is an independent
toggle. The agent name is built from `base-agent` + active layer suffixes:

```
sandbox-legion                              <- T0: no hardening (dev)
sandbox-legion-secctx                       <- T1: container hardening
sandbox-legion-secctx-landlock              <- T2: + filesystem sandbox
sandbox-legion-secctx-landlock-proxy        <- T3: + network filtering
sandbox-legion-secctx-landlock-proxy-gvisor <- T4: + kernel isolation (blocked)
```

These 5 are **presets**. The Import Wizard also lets users toggle layers
independently to build custom combos (e.g., `sandbox-legion-proxy`,
`sandbox-legion-landlock`). Unusual combinations (like proxy without secctx)
get a warning but are allowed.

---

## 2. Security Layers

Each layer is a standalone toggle. Layers are additive -- each one addresses a
different threat vector:

| Layer | Name Suffix | Mechanism | What It Adds | Overhead |
|-------|-------------|-----------|-------------|----------|
| **SecurityContext** | `-secctx` | Pod spec: non-root, drop ALL caps, seccomp RuntimeDefault, readOnlyRootFilesystem | Container breakout prevention, privilege escalation blocking | Zero (pod spec only) |
| **Landlock** | `-landlock` | `nono-launcher.py` wraps agent entrypoint; kernel-enforced filesystem restrictions via Landlock ABI v5 | Blocks `~/.ssh`, `~/.kube`, `~/.aws`, `/etc/shadow`; allows `/workspace` (RW), `/tmp` (RW), system paths (RO). **Irreversible** once applied. Bundled with TOFU hash verification (`tofu.py`) | Near-zero |
| **Proxy** | `-proxy` | Squid separate Deployment; `HTTP_PROXY`/`HTTPS_PROXY` env vars; domain allowlist | Only allowed domains reachable (GitHub, PyPI, LLM APIs); all other egress blocked. Bundled with `repo_manager.py` source policy enforcement (`sources.json`) | ~50MB RAM |
| **gVisor** | `-gvisor` | RuntimeClass `gvisor`; user-space syscall interception via runsc | Kernel exploit protection -- all syscalls handled in user space | ~100MB RAM, latency |
| **NetworkPolicy** | (always on when any layer active) | K8s NetworkPolicy: default-deny ingress/egress + DNS allow | Lateral movement prevention between pods | Zero |

---

## 3. Tier Presets

| Tier | Agent Name | Deployment | Security Layers | Use Case |
|------|-----------|------------|-----------------|----------|
| **T0** | `sandbox-legion` | K8s Deployment | None (platform auth only: Keycloak + RBAC + mTLS + HITL) | Local Kind dev, rapid prototyping |
| **T1** | `sandbox-legion-secctx` | K8s Deployment | SecurityContext + NetworkPolicy | Trusted internal agents in production |
| **T2** | `sandbox-legion-secctx-landlock` | K8s Deployment | T1 + Landlock (nono) + TOFU verification | Production agents running own code |
| **T3** | `sandbox-legion-secctx-landlock-proxy` | K8s Deployment or SandboxClaim | T2 + Squid proxy + repo_manager source policy | Imported / third-party agents |
| **T4** | `sandbox-legion-secctx-landlock-proxy-gvisor` | SandboxClaim | T3 + gVisor RuntimeClass | Arbitrary untrusted user code (blocked) |

### Security Layer x Tier Matrix

| Tier | Name | L1 Keycloak | L2 RBAC | L3 mTLS | L4 SecCtx | L5 NetPol | L6 Landlock | L7 Proxy | L8 gVisor | L9 HITL | Status |
|:----:|------|:-----------:|:-------:|:-------:|:---------:|:---------:|:-----------:|:--------:|:---------:|:-------:|--------|
| T0 | `sandbox-legion` | Y | Y | Y | -- | -- | -- | -- | -- | Y | Built |
| T1 | `sandbox-legion-secctx` | Y | Y | Y | Y | Y | -- | -- | -- | Y | Built |
| T2 | `sandbox-legion-secctx-landlock` | Y | Y | Y | Y | Y | Y | -- | -- | Y | Wired |
| T3 | `sandbox-legion-secctx-landlock-proxy` | Y | Y | Y | Y | Y | Y | Y | -- | Y | Wired |
| T4 | `sandbox-legion-secctx-landlock-proxy-gvisor` | Y | Y | Y | Y | Y | -- | Y | -- | Y | Blocked |

> **Layers L1-L3 and L9 (HITL) are always on.** Keycloak, RBAC, Istio mTLS, and
> HITL approval gates apply to all tiers. They are platform-level, not per-agent
> toggles.
>
> **Toggleable layers are L4-L8** -- these are what the wizard exposes.

---

## 4. Deployment Mechanism

The deployment mechanism is independent of security tier -- it's a separate
toggle in the wizard:

| Mode | When to Use | What It Creates |
|------|------------|----------------|
| **K8s Deployment** (default) | Persistent agents, manual wizard deploys | Standard Deployment + Service. User manages lifecycle. |
| **SandboxClaim** (opt-in) | Ephemeral agents, autonomous triggers, TTL needed | kubernetes-sigs `SandboxClaim` CRD. Controller manages lifecycle + cleanup. |

**SandboxClaim adds:**
- `lifecycle.shutdownTime` -- TTL-based auto-cleanup (default: 2 hours)
- `lifecycle.shutdownPolicy: Delete` -- pod deleted when TTL expires
- WarmPool support -- pre-warmed pods for fast start
- `triggers.py` integration -- cron/webhook/alert create SandboxClaim automatically

**kubernetes-sigs/agent-sandbox integration:**
- CRDs: `Sandbox`, `SandboxClaim`, `SandboxTemplate`, `SandboxWarmPool`
  (all installed via `35-deploy-agent-sandbox.sh`)
- Controller: StatefulSet in `agent-sandbox-system` namespace
- SandboxTemplate: deployed to `team1`/`team2` namespaces with security defaults
- SandboxClaim creation: `triggers.py` creates claims via `kubectl apply`

---

## 5. Wizard Flow

```
1. Choose base agent
   -> sandbox-legion (built-in)
   -> or Import custom agent (git URL, container image)

2. Choose security preset OR toggle individual layers:
   +---------------------------------------------------+
   |  Presets: [T0] [T1] [T2] [T3] [T4]               |
   |                                                    |
   |  Or customize:                                     |
   |  [ ] SecurityContext (non-root, caps, seccomp)     |
   |  [ ] Landlock (filesystem sandbox + TOFU)          |
   |  [ ] Proxy (domain allowlist -- configure domains) |
   |  [ ] gVisor (kernel isolation -- needs runtime)    |
   |                                                    |
   |  Warning: Proxy without SecurityContext is not     |
   |  recommended (container escape bypasses network    |
   |  filtering)                                        |
   +---------------------------------------------------+

3. Deployment mode:
   ( ) K8s Deployment (persistent, manual lifecycle)
   ( ) SandboxClaim (ephemeral, TTL auto-cleanup)
   -> If SandboxClaim: set TTL [2h]

4. Choose namespace: [team1]

5. Preview:
   Name:       sandbox-legion-secctx-landlock-proxy
   Namespace:  team1
   Deployment: SandboxClaim (TTL: 2h)
   Layers:     SecurityContext Y  Landlock Y  Proxy Y  gVisor N

6. [Deploy]
```

---

## 6. What Each Layer Wires

| Layer | Existing Code | Wiring |
|-------|--------------|--------|
| **SecurityContext** | Pod spec in sandbox-template.yaml | Already wired in wizard manifest generation |
| **Landlock** | `nono-launcher.py` (91 lines, tested) | Wraps entrypoint: `python3 nono-launcher.py python3 agent_server.py`. Requires `nono-py` pip install. |
| **TOFU** | `tofu.py` (SHA-256 hash, ConfigMap storage) | `verify_or_initialize()` before agent starts. Bundled with Landlock toggle. |
| **Proxy** | `proxy/Dockerfile` + `squid.conf` + `entrypoint.sh` | Separate Deployment per agent. `HTTP_PROXY`/`HTTPS_PROXY` env vars. Wizard configures allowed domains. |
| **repo_manager** | `repo_manager.py` + `sources.json` | Enforces `sources.json` policy on git clone. Bundled with Proxy toggle. |
| **gVisor** | RuntimeClass detection in `35-deploy-agent-sandbox.sh` | `runtimeClassName: gvisor` in pod spec. Blocked by OpenShift SELinux incompatibility. |
| **SandboxClaim** | `triggers.py` creates claims, controller deployed | Wire FastAPI `POST /api/v1/sandbox/trigger`. Wizard generates SandboxClaim YAML when toggle is on. |

---

## 7. Entrypoint by Tier

The agent container entrypoint changes based on active layers:

**T0 (no hardening):**
```bash
python3 agent_server.py
```

**T1 (secctx):**
```bash
# Same entrypoint -- SecurityContext is pod spec only
python3 agent_server.py
```

**T2 (secctx + landlock):**
```bash
pip install --target=/tmp/pip-packages --quiet nono-py
export PYTHONPATH=/tmp/pip-packages:$PYTHONPATH
# TOFU verification runs inside nono-launcher before exec
python3 nono-launcher.py python3 agent_server.py
```

**T3 (secctx + landlock + proxy):**
```bash
# Same as T2 -- proxy is a separate Deployment, not entrypoint change
pip install --target=/tmp/pip-packages --quiet nono-py
export PYTHONPATH=/tmp/pip-packages:$PYTHONPATH
export HTTP_PROXY=http://sandbox-legion-egress-proxy.team1.svc:3128
export HTTPS_PROXY=http://sandbox-legion-egress-proxy.team1.svc:3128
python3 nono-launcher.py python3 agent_server.py
```

---

## 8. Agent Profile Migration

Profiles replace the old composable-suffix naming:

| Old Name | Tier | New Profile | Changes |
|----------|------|-------------|---------|
| `sandbox-legion` | T0 | `legion` | No change |
| `sandbox-basic` | T1 | `basic` | Renamed; SecCtx was already applied |
| `sandbox-hardened` | T1 | `hardened` | Same as basic (both had SecCtx, differed only in persistence) |
| `sandbox-restricted` | T3 | `restricted` | Renamed; Landlock now wired (was missing before) |

> `sandbox-hardened` and `sandbox-basic` collapse into T1 because they differed
> only in persistence backend (PostgreSQL vs MemorySaver), not security posture.
> Persistence is orthogonal to security tier.

---

## 9. Future Runtime Isolation

| Runtime | Status | Notes |
|---------|--------|-------|
| **gVisor (runsc)** | Blocked | Incompatible with OpenShift SELinux -- gVisor rejects all SELinux labels but CRI-O always applies them. Deferred until wrapper script or upstream fix available. |
| **Kata Containers** | Planned | VM-level isolation (each pod = lightweight VM). Requires `/dev/kvm` on nodes. Strongest isolation but highest overhead (~128MB per pod). Red Hat's officially supported sandbox runtime. |

---

## Key Files

| File | Purpose |
|------|---------|
| `deployments/sandbox/nono-launcher.py` | Landlock filesystem sandbox wrapper |
| `deployments/sandbox/tofu.py` | Trust-on-first-use hash verification |
| `deployments/sandbox/repo_manager.py` | Source policy enforcement |
| `deployments/sandbox/proxy/` | Squid proxy Dockerfile + config |
| `deployments/sandbox/triggers.py` | Autonomous trigger module |
| `deployments/sandbox/sandbox-template-full.yaml` | Full SandboxTemplate with all layers |
| `.github/scripts/kagenti-operator/35-deploy-agent-sandbox.sh` | Controller deployment |
