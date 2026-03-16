# Agent Sandbox — Implementation Passover (2026-02-24)

> **For next session:** Start implementing the agent sandbox architecture based on the research document. Use this passover to get oriented, then follow the implementation order below.

## What Was Done This Session

### Research & Design Document

Created `docs/plans/2026-02-23-sandbox-agent-research.md` — a comprehensive research and design document covering:

- **12 sections**, 18 capabilities (C1-C18) with detailed deep-dives
- **7 open-source projects** deeply analyzed (repos cloned at `.worktrees/sandbox_research/`)
- **8 animated Style G diagrams** pushed to `Ladas/blog-content` asset repo
- **AuthBridge integration** documented — C6 (credential isolation), C12 (token exchange), C13 (observability) are ALREADY BUILT
- **OpenClaw security lessons** — cautionary study with CVE analysis
- **Multi-repo workflow** designed — primary repo at init, dynamic clones at runtime via AuthBridge
- **HITL delivery system** designed — multi-channel (Slack, GitHub, PagerDuty, UI, A2A) with security model
- **Capability overlaps** identified — 6 alignment patterns across the 18 capabilities
- **All links verified** — broken links fixed (agent-examples → Ladas fork, Phoenix → MLflow)
- **License audit** — all projects Apache-2.0/MIT compatible except ai-shell (no license)
- **Medium repo scripts updated** — svg-to-gif.mjs defaults to 1100px, svg-validate.sh, svg-text-check.mjs added, --check flag in svg-convert.sh

### Existing Prototype (POC)

The POC on branch `feat/sandbox-agent` validates application-level patterns only (Layer 4):
- settings.json permission model (allow/deny/HITL) ✅
- sources.json capability declaration ✅
- Per-context workspace isolation ✅
- A2A protocol + streaming ✅
- Multi-turn memory (MemorySaver) ✅
- 68 unit tests + 5 E2E tests ✅

**POC does NOT have:** gVisor/Kata, nono, AuthBridge in sandbox, Squid proxy, skills loading, TOFU, autonomous triggers, multi-repo, HITL delivery channels.

## Cluster & Environment

| Item | Value |
|------|-------|
| Cluster | `kagenti-hypershift-custom-lpvc` (2 workers, v1.33.6, Ready) |
| Kubeconfig | `~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig` |
| Agent namespace | `team1` |
| Existing sandbox-agent | deployed (POC, no AuthBridge/gVisor) |
| Worktree | `.worktrees/sandbox-agent` (branch `feat/sandbox-agent`) |
| Research repos | `.worktrees/sandbox_research/{agent-sandbox,nono,devaipod,ai-shell,paude,nanobot,openclaw}` |
| Research doc | `docs/plans/2026-02-23-sandbox-agent-research.md` |
| Diagrams | `Ladas/blog-content/kagenti/sandbox-research/*.gif` |

## Implementation Order

Based on capability dependencies and what's already built:

### Phase 1: Foundation (C1, C2, C16)

**Goal:** Deploy agent-sandbox controller, create SandboxTemplate with gVisor + hardening defaults.

1. Install agent-sandbox controller on lpvc cluster
2. Create `SandboxTemplate` with: gVisor RuntimeClass, read-only root, all caps dropped, non-root, no SA auto-mount, default-deny NetworkPolicy
3. Create a test `Sandbox` from the template — verify pod starts with gVisor
4. Verify headless Service + stable DNS

**Key files:** `.worktrees/sandbox_research/agent-sandbox/k8s/`

**OPEN ISSUE — gVisor + SELinux incompatibility (2026-02-24):**

gVisor (runsc) rejects any SELinux label. On OpenShift, CRI-O always applies SELinux process labels (`container_t`), causing `CreateContainerError`. This is fundamental — gVisor intercepts syscalls in user-space and does not implement SELinux MAC.

**Current approach: gVisor is optional, deferred to end.** Sandbox works with runc + SecurityContext hardening (C16) + nono Landlock (C3). gVisor adds C2 runtime isolation when the SELinux issue is resolved.

**What we lose disabling SELinux for sandbox pods:**
- **Mandatory Access Control (MAC)** — SELinux prevents processes from accessing files/ports/resources outside their assigned type, even if DAC (Unix permissions) would allow it
- **Container breakout prevention** — SELinux `container_t` type prevents a compromised container from accessing host files, other containers' filesystems, or sensitive kernel interfaces
- **Inter-container isolation** — MCS (Multi-Category Security) labels (`s0:c27,c24`) ensure containers in the same pod can't read each other's files

**What gVisor provides instead (stronger in many areas):**
- **Complete syscall interception** — gVisor implements its own kernel (Sentry) that intercepts ALL ~350 Linux syscalls. A compromised process can only make syscalls that gVisor explicitly implements (~70% coverage). SELinux only restricts file/network/IPC access, not arbitrary syscalls.
- **Kernel vulnerability isolation** — host kernel CVEs don't affect gVisor-sandboxed containers because they never touch the real kernel. SELinux runs on the shared kernel.
- **Reduced attack surface** — gVisor's Sentry has ~200K lines of Go vs Linux kernel's ~28M lines of C. Smaller codebase = fewer exploitable bugs.
- **Filesystem isolation** — gVisor's Gofer process mediates all filesystem access (overlay, tmpfs, bind mounts). No direct kernel VFS access.

**Why Kata Containers is the long-term solution (label: later):**
Kata provides VM-level isolation (each pod = lightweight VM with its own kernel) AND supports SELinux on the host. It's Red Hat's officially supported sandbox runtime via the OpenShift Sandboxed Containers operator. Trade-offs:
- Requires `/dev/kvm` on nodes (bare metal or metal instances on AWS) or "peer pods" mode (separate EC2 instance per sandbox, higher cost)
- 100-500ms boot overhead per pod (vs gVisor ~100ms)
- Higher memory footprint per pod (~128MB VM overhead)
- Strongest isolation of all options — full kernel boundary + SELinux + seccomp

**Recommendation:** Ship with runc + C16 + C3 now. Add gVisor (with SELinux wrapper) or Kata as optional RuntimeClass upgrades. Do NOT disable SELinux cluster-wide.

### Phase 2: Network + Auth (C5, C6, C12)

**Goal:** Add Squid proxy sidecar and verify AuthBridge token exchange works in sandbox pods.

1. Build Squid proxy sidecar container image (from paude pattern)
2. Add proxy sidecar to SandboxTemplate
3. Verify AuthBridge ext_proc works with sandbox pods (namespace label)
4. Test: agent makes GitHub API call → AuthBridge exchanges SVID → scoped token → Squid allows domain
5. Test: agent tries curl to evil.com → Squid blocks

**Key files:** `paude/containers/proxy/squid.conf`, `charts/kagenti/templates/agent-namespaces.yaml`

### Phase 3: Kernel Sandbox (C3)

**Goal:** Add nono Landlock enforcement inside the agent container.

1. Install nono Python bindings (`pip install nono-py`)
2. Wrap agent startup: `nono.sandbox()` → apply CapabilitySet → then start agent
3. Configure: allow `/workspace/**` RW, deny `~/.ssh`, `~/.kube`, `~/.aws`, `/etc/shadow`
4. Test: agent can read/write workspace; cannot read `~/.ssh`

**Key files:** `.worktrees/sandbox_research/nono/crates/nono/src/capability.rs`

### Phase 4: Skills Loading + Multi-LLM (C9, C10, C11)

**Goal:** Clone primary repo at init, load CLAUDE.md + skills, plug any LLM via litellm.

1. Add init container to SandboxTemplate: `git clone <repo-url> /workspace`
2. Build SkillsLoader: parse CLAUDE.md → system prompt, .claude/skills/ → workflow index
3. Integrate litellm: environment-variable-driven model selection
4. Test: sandbox starts, loads skills, answers questions using the repo's CLAUDE.md context
5. Test: switch LLM_MODEL env var → same skills work with different model

### Phase 5: Multi-Repo + Git Auth (C9 dynamic)

**Goal:** Agent can clone additional repos at runtime via AuthBridge.

1. Configure sources.json `allowed_remotes`: `https://github.com/kagenti/*`
2. Test: agent runs `git clone https://github.com/kagenti/kagenti-extensions` → AuthBridge injects token → clone succeeds
3. Test: agent tries to clone a repo NOT in allowed_remotes → blocked by sources.json
4. Test: agent pushes draft PR to both repos

### Phase 6: Trust Verification (C4, C15)

**Goal:** TOFU for config files, optional Sigstore attestation for instruction files.

1. Implement TOFU: hash CLAUDE.md + settings.json + sources.json on first load, store in ConfigMap
2. On subsequent sandbox creation, verify hashes match → block if changed
3. (Optional) Add Sigstore verification for CLAUDE.md in production mode

### Phase 7: Autonomous Triggers (C17)

**Goal:** Kagenti backend creates SandboxClaims from cron/webhook/alert events.

1. Add FastAPI endpoint: `POST /api/v1/sandbox/trigger` → creates SandboxClaim
2. Add cron trigger support: register schedule → backend creates SandboxClaim on tick
3. Add GitHub webhook trigger: `PR opened` → backend creates SandboxClaim with PR branch
4. Test: nightly cron → sandbox runs `/rca:ci` → pushes draft PR with findings

### Phase 8: HITL Delivery (C14, C18)

**Goal:** Multi-channel approval/conversation routing for autonomous agents.

1. Build Approval Backend in Kagenti backend (Context Registry + channel adapters)
2. Add GitHub adapter: agent posts to PR comment, human replies, routed back to contextId
3. Add Slack adapter: interactive messages with approve/deny buttons
4. Add Kagenti UI adapter: approval queue with WebSocket push
5. Test: agent hits HITL → posts to PR → human approves → agent resumes

### Phase 9: Observability (C13)

**Goal:** Verify AuthBridge OTEL root spans work with sandbox pods + MLflow.

1. Verify ext_proc creates root span with GenAI/MLflow attributes for sandbox agent
2. Verify agent's LangChain auto-instrumented spans are children of root span
3. Verify traces appear in MLflow UI
4. Run all MLflow E2E tests against sandbox agent

## Key Commands

```bash
# Source env
export MANAGED_BY_TAG=${MANAGED_BY_TAG:-kagenti-hypershift-custom}
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-lpvc/auth/kubeconfig

# Check cluster
kubectl get nodes

# Check existing sandbox agent (POC)
kubectl get pods -n team1 -l app.kubernetes.io/name=sandbox-agent
kubectl logs -n team1 deployment/sandbox-agent --tail=20

# Install agent-sandbox controller (Phase 1)
kubectl apply -f .worktrees/sandbox_research/agent-sandbox/k8s/crds/
kubectl apply -f .worktrees/sandbox_research/agent-sandbox/k8s/controller.yaml

# Run E2E tests (POC)
cd .worktrees/sandbox-agent
SANDBOX_AGENT_URL=http://localhost:8001 \
  KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml \
  uv run pytest kagenti/tests/e2e/common/test_sandbox_agent.py -v --timeout=120

# Validate SVG diagrams (medium repo)
/Users/ladas/Blogs/medium/scripts/svg-validate.sh /tmp/kagenti-sandbox-diagrams
/Users/ladas/Blogs/medium/scripts/svg-convert.sh /tmp/kagenti-sandbox-diagrams --gif --check
```

## File Map

```
docs/plans/
├── 2026-02-23-sandbox-agent-research.md    # Full research + design (this session)
├── 2026-02-24-sandbox-agent-implementation-passover.md  # This passover
├── 2026-02-14-agent-context-isolation-design.md   # Original POC design
├── 2026-02-14-agent-context-isolation-impl.md     # Original POC impl plan
└── 2026-02-18-sandbox-agent-passover.md           # Previous POC passover

.worktrees/
├── sandbox-agent/          # POC branch (feat/sandbox-agent)
└── sandbox_research/       # Cloned research repos
    ├── agent-sandbox/      # kubernetes-sigs/agent-sandbox
    ├── nono/               # always-further/nono
    ├── devaipod/           # cgwalters/devaipod
    ├── ai-shell/           # arewm/ai-shell
    ├── paude/              # bbrowning/paude
    ├── nanobot/            # HKUDS/nanobot
    └── openclaw/           # openclaw/openclaw

/tmp/kagenti-sandbox-diagrams/  # SVG sources for all 8 diagrams
```

## Startup Command for Next Session

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=${MANAGED_BY_TAG:-kagenti-hypershift-custom}
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-lpvc/auth/kubeconfig
claude
```

Then say:

> Read docs/plans/2026-02-24-sandbox-agent-implementation-passover.md and the research doc docs/plans/2026-02-23-sandbox-agent-research.md. Start implementing Phase 1 (C1, C2, C16): install agent-sandbox controller, create SandboxTemplate with gVisor + hardening defaults, test sandbox creation on the lpvc cluster.
