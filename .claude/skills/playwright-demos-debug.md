# Debug Playwright Demo Issues

Troubleshoot and fix failing Playwright walkthrough tests.

## Common Issues and Fixes

### 1. White Screen at Start
The video starts with blank page before content loads.
- **Fix**: Navigate with `page.goto()` BEFORE `markStep('intro')`

### 2. Cursor Resets to Top-Left
After `page.goto()`, the mouse position resets.
- **Fix**: Track `lastCursorX`/`lastCursorY`, pass to `injectCursor()`, restore with `page.mouse.move()`

### 3. Keycloak Auth Lost on Navigation
SPA pages lose Keycloak tokens on full reload.
- **Fix**: Use sidebar link clicks (SPA routing) instead of `page.goto()` for Kagenti UI pages
- Only use `page.goto()` for external apps (MLflow, Phoenix, Kiali)

### 4. MLflow Stuck on Welcome Page
Clicking "Experiments" matches welcome page text, not sidebar nav.
- **Fix**: Navigate directly to `${MLFLOW_URL}/#/experiments` hash URL

### 5. MLflow Popup Blocks Clicks
"GenAI apps & agents" experiment type confirmation popup.
- **Fix**: `page.getByText('Confirm').click({ force: true })` before interacting with traces

### 6. Narration Out of Sync
Narration describes actions that haven't happened yet on screen.
- **Fix**: Split long narration sections into sub-sections with matching `markStep()` calls
- Each `markStep()` should be placed RIGHT BEFORE the action it describes

### 7. Large Idle Gaps in Video
Sections where nothing happens and no narration plays.
- **Diagnose**: Check alignment table from `--sync` output
- **Fix**: Add more narration text to fill the gap, or reduce UI waits

### 8. Node.js ESM Errors
`Cannot find module` or `requires Node.js 18.19` errors.
- **Fix**: Config uses `.cjs` extension, test dirs have `package.json` with `"type": "commonjs"`

### 9. Keycloak VERIFY_PROFILE Page
New users get "Update Account Information" required action.
- **Fix**: Script auto-provisions user with email/name via Keycloak admin API
- Test handles it by filling email/firstName/lastName fields

### 10. Credentials Wrong
`keycloak-initial-admin` is master realm admin, not demo realm user.
- **Fix**: Script tries `kagenti-test-user` first (demo realm), falls back to `keycloak-initial-admin` + auto-provision

## Debugging Commands

```bash
# Dry run — see available tests and cluster info
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX>

# Check cluster credentials
oc --kubeconfig=~/clusters/hcp/kagenti-hypershift-custom-<SUFFIX>/auth/kubeconfig \
  get secret -n keycloak kagenti-test-user -o jsonpath='{.data.username}' | base64 -d

# Check MLflow auth
curl -sk https://<mlflow-url>/api/2.0/mlflow/experiments/search -X POST -H "Content-Type: application/json" -d '{}'

# View Playwright trace (from test-results)
npx playwright show-trace local_experiments/test-results/<test-dir>/trace.zip

# Screenshot a specific page for selector debugging
node -e "
const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ ignoreHTTPSErrors: true });
  await page.goto('<URL>');
  await page.screenshot({ path: '/tmp/debug.png', fullPage: true });
  const els = await page.evaluate(() =>
    Array.from(document.querySelectorAll('a, button')).map(e => ({
      tag: e.tagName, text: e.textContent?.trim()?.substring(0, 50), href: e.href
    }))
  );
  console.log(JSON.stringify(els, null, 2));
  await browser.close();
})();
"
```
