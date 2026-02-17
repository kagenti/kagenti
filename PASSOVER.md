# Passover — Playwright Demos Session 3

**Branch:** `playwright-demos`
**Worktree:** `.worktrees/playwright-demos` (run all commands from here)
**Date:** 2026-02-16
**Last commit:** pending (5th commit this session)
**CI tests run from:** `.worktrees/playwright-demos/kagenti/ui-v2/`
**Demo runner run from:** `.worktrees/playwright-demos/`

## What Was Done

### Session 3 Commits

| Commit | Description |
|--------|-------------|
| pending | Fix narration pipeline: intro overflow, timestamps flow, audio cache corruption |

### Session 2 Commits (on this branch)

| Commit | Description |
|--------|-------------|
| `fd858e7d` | Add auth to all CI tests, move demo specs to `e2e/demos/`, CI runs all tests |
| `d8d944cc` | Fix PatternFly selectors in 6 demo specs (button not link) |
| `f4225284` | Fix demo runner credential discovery (prefer keycloak-initial-admin) |
| `63b88e56` | Remove old `local_experiments/e2e/`, cleanup |

### Narration Pipeline Fixes (Session 3)

1. **Cumulative offset fix** (`sync-narration.py`) — The cumulative timing targets started from 0ms, but `markStep('intro')` fires at ~4.6s (after page load). Fixed by starting from the actual intro timestamp. This was the root cause of the intro overflow.

2. **demo-auth.ts copy** (`run-playwright-demo.sh`) — Narration-synced tests in `e2e-narration/` import `./demo-auth` but the file was never copied there. Added auto-copy before Step 3.

3. **Timestamps flow** (`run-playwright-demo.sh`) — Voiceover was using Pass 1 (fast run) timestamps instead of Pass 2 (synced run) timestamps. Added early copy of latest timestamps to demo dir before voiceover runs.

4. **Audio cache corruption** (`add-voiceover.py`) — Truncation for overflow replaced the original cached audio file, corrupting it for future runs. Fixed to use a separate `_trunc.mp3` file and keep the original intact.

## Results

### CI Tests (30/30)
- **Kind:** 30 passed (22.1s)

### Demo Specs with Narration (21/21)

All 21 demos pass the full 3-step narration pipeline on HyperShift ladas3:

| Category | Demo | Status |
|----------|------|--------|
| 01-demos | walkthrough-demo | ✓ |
| 02-ui-pages | home-overview, agent-detail, agent-build, agent-import, navigation-theme, mcp-gateway, observability, tool-detail-mcp, tool-import, admin-page | ✓ |
| 03-workflows | agent-chat, multi-namespace, tool-integration | ✓ |
| 04-observability | kiali-mesh, mcp-inspector, mlflow-traces, phoenix-realtime | ✓ |
| 05-advanced | agent-delete, env-vars, keycloak-admin | ✓ |

All 21 `_latest_voiceover.mp4` files generated with narration properly synced to video.

### Alignment Validation

Most demos show all sections OK with 0.5-1.5s idle (good). Some demos have minor (<0.5s) overlaps due to TTS variance — cosmetic, not audible.

## Known Issues

### 1. e2e-deploy — ClusterBuildStrategyNotFound
Shipwright ClusterBuildStrategy missing on ladas3. Not a test issue. Excluded from recordings.

### 2. Validation "IDLE" on `end` section
The `end` section often shows 1-3s idle because the final pause is fixed at 10s. Cosmetic only.

## Next Session Tasks

1. **PR preparation** — Squash/rebase commits, create PR against main
2. **Fix e2e-deploy** — Install ClusterBuildStrategy on ladas3 (optional)

## File Structure

```
kagenti/ui-v2/
├── e2e/
│   ├── auth.ts                    # Shared loginIfNeeded() for CI tests
│   ├── home.spec.ts               # CI test (with auth)
│   ├── agent-catalog.spec.ts      # CI test (with auth)
│   ├── tool-catalog.spec.ts       # CI test (with auth)
│   ├── agent-chat.spec.ts         # CI test (with auth)
│   ├── package.json
│   └── demos/                     # Demo specs (video recording only)
│       ├── demo-auth.ts           # Shared auth for demos
│       ├── *.spec.ts              # 22 demo spec files
│       └── package.json
├── playwright.config.ts           # CI config (testIgnore demos/)

local_experiments/
├── run-playwright-demo.sh         # Demo recorder (3-step narration pipeline)
├── sync-narration.py              # Step 2: Generate TTS + timing gates
├── add-voiceover.py               # Composite audio + video
├── validate-alignment.py          # Check narration-video alignment
├── narrations/*.txt               # Narration text files
├── e2e-narration/                 # Generated narration-synced tests
├── demos/                         # Recorded videos by category
│   ├── 01-demos/                  # Full walkthrough
│   ├── 02-ui-pages/               # Individual page demos
│   ├── 03-workflows/              # Multi-step workflows
│   ├── 04-observability/          # MLflow, Phoenix, Kiali
│   └── 05-advanced/               # Admin, env vars, delete
```

## How to Run

```bash
cd .worktrees/playwright-demos

# CI tests (Kind)
cd kagenti/ui-v2
KAGENTI_UI_URL=http://kagenti-ui.localtest.me:8080 npx playwright test

# CI tests (HyperShift)
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-ladas3/auth/kubeconfig
KAGENTI_UI_URL="https://$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')" \
KEYCLOAK_USER=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d) \
KEYCLOAK_PASSWORD=$(oc get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d) \
npx playwright test

# Demo recording (list)
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas3

# Demo recording (no narration)
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas3 --test home-overview --no-narration

# Demo recording (with narration)
source .env
./local_experiments/run-playwright-demo.sh --cluster-suffix ladas3 --test home-overview
```
