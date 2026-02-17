# Create a New Walkthrough Test

Create a new Playwright walkthrough test for recording demo videos.

## Steps

1. Create a new test file in `local_experiments/e2e/<name>.spec.ts`
2. Create matching narration in `local_experiments/narrations/<name>.txt`
3. Add description to the `get_test_description()` function in `run-playwright-demo.sh`

## Test Template

```typescript
import { test, expect } from '@playwright/test';

const PAUSE = 2000;
const LONG_PAUSE = 3000;

const UI_URL = process.env.KAGENTI_UI_URL || '';
const KC_USER = process.env.KEYCLOAK_USER || 'admin';
const KC_PASS = process.env.KEYCLOAK_PASS || 'admin';

// Timestamp tracking
const stepTimestamps: { step: string; time: number }[] = [];
const demoStartTime = Date.now();
const markStep = (step: string) => {
  const elapsed = (Date.now() - demoStartTime) / 1000;
  stepTimestamps.push({ step, time: elapsed });
  console.log(`[demo-ts] ${elapsed.toFixed(1)}s — ${step}`);
};

test.describe('Demo Name', () => {
  test.describe.configure({ mode: 'serial' });

  test('description', async ({ page }) => {
    test.setTimeout(300000);

    // Track cursor position across navigations
    let lastCursorX = 960, lastCursorY = 540;

    // Inject cursor follower (copy from walkthrough-demo.spec.ts)
    const injectCursor = async () => { /* ... */ };
    const humanMove = async (toX: number, toY: number) => { /* ... */ };
    const demoClick = async (locator: any, description?: string) => { /* ... */ };

    // Navigate and mark steps
    await page.goto(UI_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await injectCursor();
    markStep('intro');

    // ... test steps with markStep() at each section boundary ...

    markStep('end');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const tsFile = path.join(process.env.PLAYWRIGHT_OUTPUT_DIR || '.', '..', '<name>-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
  });
});
```

## Key Patterns

### SPA Navigation (Kagenti UI)
Use sidebar clicks instead of `page.goto()` to preserve Keycloak tokens:
```typescript
const link = page.locator('nav a').filter({ hasText: /^Agents$/ });
await demoClick(link.first(), 'Agents sidebar');
```

### Full Page Navigation (MLflow, Phoenix, Kiali)
Use `page.goto()` + `injectCursor()`:
```typescript
await page.goto(MLFLOW_URL, { waitUntil: 'networkidle', timeout: 30000 });
await injectCursor();
```

### Auth Handling
- Kagenti: click Sign In → Keycloak form → handle VERIFY_PROFILE
- MLflow: click Keycloak SSO button on OIDC login page
- Kiali: kubeadmin OAuth login with identity provider selection

### Section Granularity
Each `markStep()` should correspond to a distinct visual state in the video.
If narration for one step is > 10s, split into sub-steps.

## Narration File Format

```
[intro]
Description of what's shown on screen during this section.

[step_name]
Match section names to markStep() calls in the test.
```

## Running

```bash
# Fast recording (no narration)
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test <name>

# With synced narration
source .env
./local_experiments/run-playwright-demo.sh --cluster-suffix <SUFFIX> --test <name> --sync
```
