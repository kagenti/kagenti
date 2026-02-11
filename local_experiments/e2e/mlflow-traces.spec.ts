/**
 * Kagenti MLflow Trace Analysis Deep Dive Demo
 *
 * A detailed exploration of MLflow experiment traces:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to MLflow (page.goto MLFLOW_URL)
 *   3. Handle MLflow OIDC login (2-stage: MLflow OIDC page -> Keycloak)
 *   4. Navigate to experiments list
 *   5. Open Default experiment, dismiss GenAI popup
 *   6. Click Traces tab
 *   7. Click first trace to see detail (span tree)
 *   8. Hover over span details
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 *   MLFLOW_URL       - MLflow UI URL
 */
import { test, expect } from '@playwright/test';

const PAUSE = 2000;
const LONG_PAUSE = 3000;

// Timestamp tracking for narration sync
const stepTimestamps: { step: string; time: number }[] = [];
const demoStartTime = Date.now();
const markStep = (step: string) => {
  const elapsed = (Date.now() - demoStartTime) / 1000;
  stepTimestamps.push({ step, time: elapsed });
  console.log(`[demo-ts] ${elapsed.toFixed(1)}s — ${step}`);
};

const UI_URL = process.env.KAGENTI_UI_URL || '';
const KC_USER = process.env.KEYCLOAK_USER || 'admin';
const KC_PASS = process.env.KEYCLOAK_PASS || 'admin';
const MLFLOW_URL = process.env.MLFLOW_URL || '';

test.describe('MLflow Trace Analysis Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('MLflow traces: login, experiments, trace detail, spans', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes for MLflow auth flows

    // ================================================================
    // Cursor tracking and injection
    // ================================================================
    let lastCursorX = 960;
    let lastCursorY = 540;

    const injectCursor = async () => {
      await page.evaluate(([startX, startY]) => {
        if (document.getElementById('pw-cursor')) return;
        const cursor = document.createElement('div');
        cursor.id = 'pw-cursor';
        cursor.style.cssText = `
          width: 20px; height: 20px;
          background: rgba(255, 50, 50, 0.7);
          border: 2px solid rgba(255, 255, 255, 0.9);
          border-radius: 50%;
          position: fixed;
          top: ${startY - 10}px; left: ${startX - 10}px;
          z-index: 999999;
          pointer-events: none;
          transition: transform 0.15s ease;
          box-shadow: 0 0 8px rgba(0,0,0,0.4);
        `;
        document.body.appendChild(cursor);
        document.addEventListener('mousemove', (e) => {
          cursor.style.left = (e.clientX - 10) + 'px';
          cursor.style.top = (e.clientY - 10) + 'px';
        });
        document.addEventListener('mousedown', () => {
          cursor.style.transform = 'scale(0.7)';
          cursor.style.background = 'rgba(255, 50, 50, 0.95)';
        });
        document.addEventListener('mouseup', () => {
          cursor.style.transform = 'scale(1)';
          cursor.style.background = 'rgba(255, 50, 50, 0.7)';
        });
      }, [lastCursorX, lastCursorY]);
      await page.mouse.move(lastCursorX, lastCursorY);
    };

    page.on('load', async () => {
      await injectCursor().catch(() => {});
    });

    const humanMove = async (toX: number, toY: number) => {
      await page.mouse.move(toX, toY, { steps: 25 });
      lastCursorX = toX;
      lastCursorY = toY;
    };

    const demoClick = async (locator: any, description?: string) => {
      if (description) console.log(`[demo] Clicking: ${description}`);
      await locator.scrollIntoViewIfNeeded().catch(() => {});
      const box = await locator.boundingBox();
      if (box) {
        const offsetX = (Math.random() - 0.5) * box.width * 0.2;
        const offsetY = (Math.random() - 0.5) * box.height * 0.2;
        await humanMove(box.x + box.width / 2 + offsetX, box.y + box.height / 2 + offsetY);
        await page.waitForTimeout(200);
      }
      await locator.click();
    };

    // ================================================================
    // STEP 1: Navigate to Kagenti UI
    // ================================================================
    console.log('[demo] Step 1: Navigate to Kagenti UI');
    await page.goto(UI_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await injectCursor();
    markStep('intro');
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 2: Login via Keycloak (if needed)
    // ================================================================
    markStep('login');
    console.log('[demo] Step 2: Login via Keycloak');
    const loginButton = page.getByRole('button', { name: /sign in|login|log in/i })
      .or(page.getByRole('link', { name: /sign in|login|log in/i }));

    if (await loginButton.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(loginButton.first(), 'Sign In button');

      await page.waitForURL(
        (url) => url.toString().includes('/realms/'),
        { timeout: 15000 }
      );
      await page.waitForSelector('#username', { timeout: 10000 });
      await page.waitForTimeout(PAUSE);

      await page.fill('#username', KC_USER);
      await page.waitForTimeout(500);
      await page.fill('#password', KC_PASS);
      await page.waitForTimeout(500);
      await demoClick(page.locator('#kc-login'), 'Keycloak Sign In');

      // Handle VERIFY_PROFILE
      await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
      if (page.url().includes('VERIFY_PROFILE') || page.url().includes('required-action')) {
        const emailField = page.locator('#email');
        if (await emailField.isVisible({ timeout: 2000 }).catch(() => false)) {
          if (!(await emailField.inputValue())) await emailField.fill('admin@kagenti.local');
        }
        const firstNameField = page.locator('#firstName');
        if (await firstNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          if (!(await firstNameField.inputValue())) await firstNameField.fill('Admin');
        }
        const lastNameField = page.locator('#lastName');
        if (await lastNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          if (!(await lastNameField.inputValue())) await lastNameField.fill('User');
        }
        const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
        if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
          await submitBtn.click();
        }
      }

      await page.waitForURL(
        (url) => url.toString().startsWith(UI_URL) && !url.toString().includes('/realms/'),
        { timeout: 30000 }
      );
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      console.log('[demo] Login successful');
    } else {
      console.log('[demo] No login button — auth disabled');
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ASSERT: We're on the Kagenti UI (not stuck on Keycloak)
    expect(page.url()).not.toContain('/realms/');

    // ================================================================
    // STEP 3: Navigate to MLflow
    // ================================================================
    markStep('mlflow_navigate');

    if (MLFLOW_URL) {
      console.log('[demo] Step 3: Navigate to MLflow');
      await page.goto(MLFLOW_URL, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(2000);

      // ================================================================
      // STEP 4: Handle MLflow OIDC login (2-stage)
      // ================================================================
      markStep('mlflow_login');

      // Stage 1: MLflow's OIDC login page — find and click any sign-in element
      if (page.url().includes('/oidc/') || page.url().includes('/auth') || page.url().includes('login')) {
        console.log('[demo] MLflow login page detected');
        await injectCursor();
        await page.waitForTimeout(LONG_PAUSE);

        const signInSelectors = [
          page.getByRole('button', { name: /sign in|login|log in/i }),
          page.getByRole('link', { name: /sign in|login|log in|keycloak|oidc/i }),
          page.locator('a:has-text("Sign in")'),
          page.locator('a:has-text("Login")'),
          page.locator('button:has-text("Sign in")'),
          page.locator('input[type="submit"]'),
          page.locator('a[href*="oidc"]'),
          page.locator('a[href*="login"]'),
          page.locator('form input[type="submit"], form button[type="submit"]'),
        ];

        let clicked = false;
        for (const selector of signInSelectors) {
          if (await selector.first().isVisible({ timeout: 1000 }).catch(() => false)) {
            const text = await selector.first().textContent().catch(() => '');
            await demoClick(selector.first(), `MLflow login (${text?.trim()})`);
            clicked = true;
            await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
            await page.waitForTimeout(1000);
            break;
          }
        }

        if (!clicked) {
          const allLinks = await page.evaluate(() => {
            return Array.from(document.querySelectorAll('a, button, input')).map(e => ({
              tag: e.tagName, text: (e as any).textContent?.trim()?.substring(0, 50),
              href: (e as any).href || '', type: (e as any).type || ''
            }));
          });
          console.log(`[demo] No MLflow sign-in element found. Page elements: ${JSON.stringify(allLinks.slice(0, 10))}`);
          await page.waitForTimeout(PAUSE);
        }
      }

      // Stage 2: Keycloak login page (if not auto-logged in from existing session)
      if (page.url().includes('/realms/')) {
        console.log('[demo] MLflow redirected to Keycloak');
        const kcUsername = page.locator('#username');
        if (await kcUsername.isVisible({ timeout: 5000 }).catch(() => false)) {
          await page.fill('#username', KC_USER);
          await page.fill('#password', KC_PASS);
          await demoClick(page.locator('#kc-login'), 'MLflow Keycloak login');

          // Handle VERIFY_PROFILE if needed
          await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
          if (page.url().includes('required-action')) {
            const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
            if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
              await submitBtn.click();
            }
          }
        }

        // Wait for redirect back to MLflow
        await page.waitForURL(
          (url) => !url.toString().includes('/realms/'),
          { timeout: 30000 }
        ).catch(() => {});
      }

      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

      // After OIDC login, MLflow may land on callback page — navigate to root
      if (!page.url().includes('#/experiments') && !page.url().endsWith('/')) {
        console.log(`[demo] MLflow post-login URL: ${page.url()}, navigating to root...`);
        await page.goto(MLFLOW_URL, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      }

      await injectCursor();
      console.log(`[demo] MLflow loaded: ${page.url()}`);
      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 5: Navigate to experiments list
      // ================================================================
      markStep('mlflow_experiments');
      console.log('[demo] Step 5: Navigate to MLflow experiments');
      await page.goto(`${MLFLOW_URL}/#/experiments`, { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);
      console.log(`[demo] MLflow experiments: ${page.url()}`);

      // Click on "Default" experiment (experiment ID 0)
      const defaultExp = page.locator('a[href*="#/experiments/"]').first();
      // ASSERT: At least one experiment must be visible in MLflow
      await expect(defaultExp).toBeVisible({ timeout: 8000 });
      await demoClick(defaultExp, 'Default experiment');
      await page.waitForTimeout(LONG_PAUSE);

      // Dismiss the "GenAI apps & agents" experiment type popup if present
      const confirmBtn = page.getByText('Confirm', { exact: true });
      if (await confirmBtn.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await confirmBtn.first().click({ force: true });
        console.log('[demo] Dismissed MLflow experiment type popup');
        await page.waitForTimeout(500);
      }

      await page.waitForTimeout(PAUSE);

      // ================================================================
      // STEP 6: Click Traces tab
      // ================================================================
      markStep('mlflow_traces');
      console.log('[demo] Step 6: Click Traces tab');

      const tracesTab = page.locator('a[href*="/traces"]')
        .or(page.getByRole('tab', { name: /Traces/i }));
      if (await tracesTab.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(tracesTab.first(), 'Traces tab');
        await page.waitForTimeout(LONG_PAUSE);
      } else {
        // Try direct hash navigation to traces
        console.log('[demo] Traces tab not found, navigating directly');
        await page.goto(`${MLFLOW_URL}/#/experiments/0/traces`, { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
        await injectCursor();
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Dismiss popup if it appeared after navigating to traces
      const confirmBtn2 = page.getByText('Confirm', { exact: true });
      if (await confirmBtn2.first().isVisible({ timeout: 1000 }).catch(() => false)) {
        await confirmBtn2.first().click({ force: true });
        await page.waitForTimeout(500);
      }

      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 7: Click first trace to see detail (span tree)
      // ================================================================
      markStep('mlflow_trace_detail');
      console.log('[demo] Step 7: Click first trace for detail view');

      const traceSelectors = [
        page.locator('a:has-text("tr-")').first(),
        page.locator('[role="row"] a').first(),
        page.locator('table a').first(),
      ];
      let traceClicked = false;
      for (const sel of traceSelectors) {
        if (await sel.isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(sel, 'Latest trace');
          traceClicked = true;
          break;
        }
      }
      if (traceClicked) {
        await page.waitForTimeout(5000);
        console.log('[demo] Showing trace detail with span tree');
      } else {
        console.log('[demo] No trace links found');
      }
      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 8: Hover over span details
      // ================================================================
      markStep('mlflow_spans');
      console.log('[demo] Step 8: Hover over span details');

      // Look for span tree nodes or detail panels
      const spanNodes = page.locator('[class*="span"], [class*="tree"] [role="treeitem"], [class*="node"]');
      const spanCount = await spanNodes.count();
      console.log(`[demo] Found ${spanCount} span-like elements`);

      for (let i = 0; i < Math.min(spanCount, 5); i++) {
        const span = spanNodes.nth(i);
        if (await span.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await span.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(800);
          }
        }
      }

      // Also hover over any detail panels (attributes, timing info)
      const detailPanels = page.locator('[class*="detail"], [class*="attributes"], [class*="info-panel"]');
      const detailCount = await detailPanels.count();
      for (let i = 0; i < Math.min(detailCount, 3); i++) {
        const panel = detailPanels.nth(i);
        if (await panel.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await panel.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(800);
          }
        }
      }

      // Scroll down to see more span details
      await page.mouse.wheel(0, 300);
      await page.waitForTimeout(PAUSE);
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);

    } else {
      console.log('[demo] MLflow URL not set, skipping MLflow sections');
      markStep('mlflow_login');
      markStep('mlflow_experiments');
      markStep('mlflow_traces');
      markStep('mlflow_trace_detail');
      markStep('mlflow_spans');
    }

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] MLflow trace analysis demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'mlflow-traces-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
