---
name: tdd:ui-hypershift
description: Rapid UI/backend iteration on HyperShift — edit, build, deploy, Playwright test in under 3 minutes
---

# TDD UI+Backend on HyperShift

Fast iteration loop for Rossoctl UI and backend development on a live HyperShift cluster.
Covers the full cycle: edit → commit → push → build → rollout → Playwright test.

## When to Use

- Fixing UI rendering bugs (SandboxPage, ChatBubble, etc.)
- Fixing backend API issues (sandbox_deploy, chat streaming)
- Adding new UI features and testing on live cluster
- Iterating on Playwright E2E tests

## Setup (once per session)

```bash
# Cluster config
export CLUSTER=sbox42
export MANAGED_BY_TAG=rossoctl-team
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-${CLUSTER}/auth/kubeconfig
export LOG_DIR="${LOG_DIR:-/tmp/rossoctl/tdd/ui-${CLUSTER}}"
mkdir -p "$LOG_DIR"

# Keycloak password (stored in K8s secret, not hardcoded)
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret rossoctl-test-users \
  -o jsonpath='{.data.admin-password}' | base64 -d)

# UI URL from OpenShift route
export ROSSOCTL_UI_URL="https://$(kubectl get route rossoctl-ui -n rossoctl-system \
  -o jsonpath='{.spec.host}')"

# Working directory
cd "${WORKTREE_DIR:-.worktrees/sandbox-agent}"/rossoctl/ui-v2
```

## Iteration Levels (fastest first)

### Level 0: Test-only change (~30s)

Test file changed, no build needed:

```bash
KUBECONFIG=$KUBECONFIG ROSSOCTL_UI_URL=$ROSSOCTL_UI_URL \
  KEYCLOAK_USER=admin KEYCLOAK_PASSWORD=$KEYCLOAK_PASSWORD \
  npx playwright test e2e/<spec>.spec.ts --reporter=list \
  > $LOG_DIR/test.log 2>&1; echo "EXIT:$?"
```

### Level 1: UI-only change (~2min)

Frontend code changed (components, pages, styles):

```bash
# 1. Commit + push
git add -u && git commit -s -m "fix(ui): <description>" && git push

# 2. Build UI image (~90s)
oc -n rossoctl-system start-build rossoctl-ui > $LOG_DIR/ui-build.log 2>&1
# Poll until complete:
while ! oc -n rossoctl-system get build rossoctl-ui-$(oc -n rossoctl-system get bc rossoctl-ui -o jsonpath='{.status.lastVersion}') -o jsonpath='{.status.phase}' 2>/dev/null | grep -qE 'Complete|Failed'; do sleep 10; done
echo "Build: $(oc -n rossoctl-system get build rossoctl-ui-$(oc -n rossoctl-system get bc rossoctl-ui -o jsonpath='{.status.lastVersion}') -o jsonpath='{.status.phase}')"

# 3. Rollout (~15s)
oc -n rossoctl-system rollout restart deploy/rossoctl-ui
oc -n rossoctl-system rollout status deploy/rossoctl-ui --timeout=60s

# 4. Test
npx playwright test e2e/<spec>.spec.ts --reporter=list > $LOG_DIR/test.log 2>&1; echo "EXIT:$?"
```

### Level 2: Backend-only change (~90s)

Backend Python code changed (routers, services):

```bash
# 1. Commit + push
git add -u && git commit -s -m "fix(backend): <description>" && git push

# 2. Build backend image (~30s — Python, no npm)
oc -n rossoctl-system start-build rossoctl-backend > $LOG_DIR/be-build.log 2>&1
# Wait for completion (same polling pattern as UI)

# 3. Rollout
oc -n rossoctl-system rollout restart deploy/rossoctl-backend
oc -n rossoctl-system rollout status deploy/rossoctl-backend --timeout=90s

# 4. Test
npx playwright test e2e/<spec>.spec.ts --reporter=list > $LOG_DIR/test.log 2>&1; echo "EXIT:$?"
```

### Level 3: Both UI + backend (~3min)

```bash
git add -u && git commit -s -m "fix: <description>" && git push

# Build both in parallel
oc -n rossoctl-system start-build rossoctl-backend &
oc -n rossoctl-system start-build rossoctl-ui &
wait
# Poll both until complete, then:

oc -n rossoctl-system rollout restart deploy/rossoctl-backend deploy/rossoctl-ui
oc -n rossoctl-system rollout status deploy/rossoctl-backend --timeout=90s
oc -n rossoctl-system rollout status deploy/rossoctl-ui --timeout=90s

# Test
npx playwright test e2e/<spec>.spec.ts --reporter=list > $LOG_DIR/test.log 2>&1; echo "EXIT:$?"
```

## Common Patterns

### Agent cleanup before test

```bash
oc -n team1 delete deploy ${AGENT_NAME} --ignore-not-found
oc -n team1 delete svc ${AGENT_NAME} --ignore-not-found
```

### Check pod crash reason

```bash
oc -n rossoctl-system logs deploy/rossoctl-backend -c backend --tail=20
oc -n team1 describe pod -l app.kubernetes.io/name=${AGENT_NAME} | grep -A5 "Events\|Error"
```

### Build failure diagnosis

```bash
oc -n rossoctl-system logs build/rossoctl-ui-$(oc -n rossoctl-system get bc rossoctl-ui -o jsonpath='{.status.lastVersion}') | tail -20
```

### SPA routing for session reload (Keycloak redirect workaround)

In Playwright tests, navigating to `/sandbox?session=<id>` via `page.goto()` triggers
Keycloak re-auth which redirects to `/`. Use SPA routing instead:

```typescript
// Login first on /
await page.goto('/');
await loginIfNeeded(page);
// Then SPA-navigate (no full page reload, no Keycloak redirect)
await page.evaluate((sid) => {
  window.history.pushState({}, '', `/sandbox?session=${sid}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}, sessionId);
```

## Checklist

Before each iteration:
- [ ] Changes committed and pushed (build configs pull from git)
- [ ] Correct KUBECONFIG exported
- [ ] KEYCLOAK_PASSWORD refreshed (passwords rotate)
- [ ] Previous test agent cleaned up (if applicable)

After green tests:
- [ ] Push final commit
- [ ] Run full suite: `npx playwright test --reporter=list`
- [ ] Check for regressions in other spec files

## Related Skills

- `test:ui` — Playwright test writing patterns and selectors
- `tdd:hypershift` — Python E2E tests via hypershift-full-test.sh
- `rossoctl:ui-debug` — Debug 502s, proxy issues, auth problems
- `k8s:live-debugging` — Debug pods, logs, configs on live cluster
