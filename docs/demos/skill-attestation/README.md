# Weather-Agent Skill-Integrity Gate — gate-only demo (Kind)

A local, RHTAS-free recreation of the **tamper-evident core** of the
*SPIFFE Workload Identity–Bound Agent Skill Integrity* demo
(R. Chang · M. Sabath · M. Iyer · J. Cwiklik et al., 2026-07-01; kagenti epic
[#2074](https://github.com/kagenti/kagenti/issues/2074)).

## What this shows

An agent's skill files are hashed into a **pinned digest**. At pod startup an
init container recomputes the digest over the skills it's about to load and
compares it to the pinned value:

- **match** → gate exits 0, the agent container starts;
- **mismatch** (a skill was modified, or the pinned digest was flipped) → gate
  exits 1, the pod is wedged in `Init:Error`, **the agent never starts**.

```
snapshot-skills ─► skill-integrity-gate ─► agent
   cp /app→emptyDir    skill-hash verify      starts only if the gate passed
```

Because it's a rolling update, the previous good pod keeps serving until the new
one passes — a failed gate never causes an outage.

## What this deliberately OMITS (vs. the full demo)

The full demo adds two more init containers — `skill-attestor-sign` and
`skill-attestation-verify` — that mint the agent's **SPIFFE JWT-SVID**, use
`cosign` to **keyless-sign** the verified manifest against **RHTAS/Sigstore**
(Fulcio + Rekor + TUF), and record an immutable transparency-log entry whose
signer SAN *is* the workload's SPIFFE ID.

Those steps need RHTAS, which **Kagenti does not install** (it ships SPIRE but no
Sigstore). The full flow was demoed on an OpenShift cluster (`ykt2`) with the
RHTAS operator. This gate-only version drops signing + the Rekor audit trail and
keeps the fail-closed integrity gate, which is the part that blocks a tampered
skill. See `docs/` references below to extend it to the full pipeline.

## Components

| Piece | Image / source | Role |
|-------|----------------|------|
| stand-in agent | built here from `Dockerfile.agent` (ubi9-minimal, skills baked at `/app`) | proves the gate released it; **not** the real LLM agent |
| integrity gate | `ghcr.io/webchang/skill-hash:0.1.0` (reused as-is) | `skill-hash verify` — recompute & compare the pinned digest |
| skill collection | `agent-examples/a2a/weather_service` (exported at run time) | `README.md`, `Dockerfile`, `src/weather_service/` |

The skill collection is **not vendored** into this repo — `run.sh` exports it
fresh from your `agent-examples` clone at run time (`git archive HEAD:a2a/weather_service`,
exactly as the design PDF does) into a gitignored `.skills/` working copy. This
avoids duplicating source and keeps it out of repo-wide linting.

The trusted digest is **not hardcoded**: `run.sh up` computes it by running the
real `skill-hash` image over the exported files, so nothing outside that image
is in the trust path.

## Prerequisites

Run on the **host** (a sandboxed session cannot reach the podman machine):

- a running container engine — `podman machine start` (or Docker; `ENGINE=docker ./run.sh …`)
- `kind` and `kubectl` on PATH
- an `agent-examples` clone; if it isn't at `../../../../agent-examples`, set
  `AGENT_EXAMPLES=/path/to/agent-examples`

## Run it

```bash
cd docs/demos/skill-attestation

./run.sh up        # kind cluster + build + compute/pin digest + deploy; waits until Ready
./run.sh tamper    # modifies a skill file, rolls out; new pod wedges in Init:Error
./run.sh logs      # shows the gate's "FAILED: digest mismatch"
./run.sh restore   # reverts the skill; gate passes; agent Running again
./run.sh down      # tear down
```

### Expected output

`up` → the gate prints `PASSED: digests match` and the pod goes `Running`; the
agent logs `[agent] skill-integrity gate passed — weather agent starting`.

`tamper` → the new pod's `skill-integrity-gate` prints
`FAILED: digest mismatch` and the pod stays in `Init:Error`; the old pod keeps
running.

## Files

- `run.sh` — host-side driver (up / tamper / restore / logs / down)
- `Dockerfile.agent` — stand-in agent, bakes the exported skills at `/app`
- `deployment.yaml.tmpl` — Deployment; `__SKILL_DIGEST__` filled in by `run.sh`
- `.skills/` — gitignored; the weather skill collection exported at run time

## References

- Design PDF: *SPIFFE Workload Identity–Bound Agent Skill Integrity* (attached to epic #2074)
- Draft epic: kagenti#2074 (note: the epic proposes a `ClusterStaticEntry` +
  AuthBridge-egress enforcement mechanism; the implemented demo above enforces at
  pod-startup via init containers instead — same goal, different enforcement point)
- Tooling: `github.com/webchang/skill-hash`, `github.com/webchang/skill-attestor`
