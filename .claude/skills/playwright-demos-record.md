# Record a Playwright Demo Video

Record a walkthrough video of the Kagenti platform against a live cluster.

## Usage

```bash
# From the playwright-demos worktree:
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test walkthrough-demo

# Dry run (list available tests):
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX>

# Run all tests:
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --all
```

## What the Script Does

1. Discovers UI URL from cluster routes (HyperShift or Kind)
2. Discovers Keycloak credentials from `kagenti-test-user` secret (falls back to `keycloak-initial-admin`)
3. Auto-provisions demo realm user if needed (via Keycloak admin API)
4. Discovers MLflow, Kiali, Phoenix URLs from routes
5. Discovers kubeadmin password for Kiali OAuth
6. Runs npm audit for vulnerabilities
7. Generates a temporary Playwright config with video recording enabled (1920x1080)
8. Runs the Playwright test with headless Chromium
9. Collects and renames video files with timestamp

## Output

```
local_experiments/walkthrough-demo-..._YYYY-MM-DD_HH-MM.webm   # Raw video
```

## Walkthrough Test Steps

The `walkthrough-demo.spec.ts` test performs:

1. Navigate to Kagenti UI
2. Login via Keycloak (click Sign In → fill credentials → handle VERIFY_PROFILE)
3. Navigate to Agent Catalog (SPA sidebar click, select team1 namespace)
4. Open weather-service agent detail page
5. Chat tab → send "What is the weather in San Francisco?" → wait for response
6. Navigate to MLflow → OIDC login → experiments → traces → trace detail
7. Navigate to Phoenix → traces → trace detail
8. Navigate to Kiali → kubeadmin OAuth → Traffic Graph → select all namespaces → Last 10m → Security + Animation toggles

## Key Technical Details

- Uses SPA client-side navigation for Kagenti UI (avoids full page reload losing Keycloak tokens)
- Injects a visible CSS cursor follower (headless Playwright doesn't render cursor)
- Uses `page.mouse.move()` with `steps: 25` for smooth cursor movement
- Tracks cursor position across page navigations (no reset to top-left)
- MLflow uses hash routing (`#/experiments`) — navigate directly via URL
- Kiali requires separate kubeadmin OAuth login
- Node.js ESM workaround: generates `.cjs` config and `package.json` with `"type": "commonjs"` in test dirs

## Troubleshooting

| Issue | Fix |
|-------|-----|
| White screen at start | Test navigates immediately before `markStep('intro')` |
| Auth lost on navigation | SPA sidebar clicks instead of `page.goto()` for Kagenti pages |
| MLflow stuck on welcome | Navigate directly to `#/experiments` hash URL |
| MLflow popup blocks clicks | Dismiss "Confirm" button with `force: true` |
| Keycloak VERIFY_PROFILE | Auto-fills email/name fields and submits |
| npm ESM error | Config uses `.cjs` extension with CommonJS require |
