# Passover: Playwright Demo + UI Test Unification

## What's Done

### PR #681 (Merged)
- `agent-chat.spec.ts` in `kagenti/ui-v2/e2e/` — login, navigate to agent, chat, verify response
- `91-run-ui-tests.sh` CI script — auto-detects env (Kind/HyperShift), credentials, UI URL
- Shared `loginIfNeeded()` works on both Kind (check-sso) and HyperShift (login-required, Red Hat Keycloak)
- `ignoreHTTPSErrors: true` in playwright config for HyperShift
- Tests pass on Kind CI, local Kind, and HyperShift (ladas3)

### Demo Specs Refactored
- Created `local_experiments/e2e/demo-auth.ts` — shared login helper with `demoLogin(page, demoClick?)`
- All 22 demo specs updated to `import { demoLogin } from './demo-auth'`
- Removed ~1200 lines of duplicated inline login code
- Handles: community Keycloak, Red Hat Keycloak, VERIFY_PROFILE page, `pressSequentially` for password
- Env vars: `KEYCLOAK_USER`, `KEYCLOAK_PASSWORD` (with `KEYCLOAK_PASS` backward compat)

### Rebase
- `playwright-demos` branch rebased onto `upstream/main` (includes PR #679 keycloak fix, #680 dockerhost fix, #681 UI test)
- Stashed narration trims applied

### Demo Recordings (from prior session)
- 6 demos re-recorded with timing gate fix (all pass)
- Walkthrough demo recorded (96% coverage, no crash)
- agent-import, agent-build, tool-integration narrations trimmed for alignment

## What's Blocked

### `demo-auth.ts` import broken in demo runner
`run-playwright-demo.sh` generates a temp CJS config and copies spec files individually.
The `import { demoLogin } from './demo-auth'` breaks because `demo-auth.ts` isn't copied alongside.

## What Needs Doing

### 1. Restructure test file locations
Move demo test specs from `local_experiments/e2e/` to `kagenti/ui-v2/e2e/` alongside the merged `agent-chat.spec.ts`.

```
kagenti/ui-v2/e2e/
├── demo-auth.ts              # shared login helper (move from local_experiments/e2e/)
├── agent-chat.spec.ts        # merged PR #681 (already here)
├── agent-catalog.spec.ts     # existing (needs auth update)
├── tool-catalog.spec.ts      # existing (needs auth update)
├── home.spec.ts              # existing (needs auth update)
├── demos/                    # demo-specific specs (for video recording)
│   ├── home-overview.spec.ts
│   ├── agent-build.spec.ts
│   ├── ... (all 22 demo specs)
│   └── walkthrough-demo.spec.ts
```

### 2. Two Playwright configs
- `playwright.config.ts` — CI/test mode (headless, fast, no video, retries)
- `playwright-video.config.ts` — demo recording mode (video on, slowMo, cursor, no retries)

Both should use the same test directory and share `demo-auth.ts`.

### 3. Update `run-playwright-demo.sh`
- Don't copy spec files to temp location
- Point `PLAYWRIGHT_TEST_DIR` to `kagenti/ui-v2/e2e/demos/`
- Use `playwright-video.config.ts` from `kagenti/ui-v2/`

### 4. Update existing tests (agent-catalog, tool-catalog, home)
These are the 11 tests that fail in CI because they don't handle auth.
Import `demoLogin` (or a simpler `loginIfNeeded`) and add login to `beforeEach`.

### 5. Test on both environments
```bash
# Kind
KAGENTI_UI_URL=http://kagenti-ui.localtest.me:8080 npx playwright test --reporter=list

# HyperShift
KAGENTI_UI_URL="https://$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')" \
KEYCLOAK_USER="temp-admin" KEYCLOAK_PASSWORD="<from secret>" \
npx playwright test --reporter=list
```

### 6. Fix e2e-deploy (task #4 from prior session)
`e2e-deploy` test fails on ladas1 due to `ClusterBuildStrategyNotFound`.
Need `buildah-insecure-push` ClusterBuildStrategy or change test to use pre-built image.

## Key Findings from This Session

### Issue #678 Root Cause
Backend used external Keycloak URL (`keycloak.localtest.me:8080`) for JWKS token validation.
This URL is unreachable from inside cluster pods -> `httpx.ConnectError` -> 500 on all authenticated API calls.
**Fixed by PR #679** (merged) -- `keycloak_internal_url` property uses in-cluster DNS when running in-cluster.

### HyperShift Login Issues
- Username is `temp-admin` (not `admin`) -- read from `keycloak-initial-admin` secret
- Red Hat Keycloak password field requires `pressSequentially()` -- `fill()` doesn't work
- `#kc-login` button ID may not exist -- need fallback to `button[type="submit"]`
- VERIFY_PROFILE page appears on first login -- fill email/name fields

### Playwright Version
- Node 19.1 on local machine -> Playwright ^1.50.0 resolves to 1.58 which requires Node 18.19+
- Pinned to `~1.50.0` for compatibility
- CI (Node 20) works with latest

## Cluster Info

| Cluster | Status | Kubeconfig |
|---------|--------|------------|
| Kind (`kagenti`) | Running | default context |
| HyperShift `ladas3` | Running (use `oc` not `kubectl`) | `~/clusters/hcp/kagenti-hypershift-custom-ladas3/auth/kubeconfig` |

## Git Status

```
playwright-demos branch: rebased on upstream/main (ea784661)
  - 10 commits ahead (demo recording infra)
  - Uncommitted: demo-auth.ts + 22 spec refactors + trimmed narrations
```

Stash the uncommitted work or commit before next session:
```bash
cd .worktrees/playwright-demos
git add local_experiments/e2e/demo-auth.ts local_experiments/e2e/*.spec.ts local_experiments/narrations/
git commit -s -m "refactor: Extract shared demoLogin helper, trim narrations"
```

## Key Files

| File | Purpose |
|------|---------|
| `local_experiments/e2e/demo-auth.ts` | Shared login helper (NEW) |
| `local_experiments/run-demo-quiet.sh` | Run one test, log to file |
| `local_experiments/run-playwright-demo.sh` | Full pipeline (3-step with TTS) |
| `local_experiments/sync-narration.py` | Timing gate injection |
| `local_experiments/add-voiceover.py` | TTS generation + FFmpeg compositing |
| `local_experiments/demo-map.json` | Test name -> nested output dir mapping |
| `local_experiments/validate-alignment.py` | Check narration-video alignment |
| `kagenti/ui-v2/e2e/agent-chat.spec.ts` | Merged UI test (PR #681) |
| `.github/scripts/common/91-run-ui-tests.sh` | CI UI test runner |
