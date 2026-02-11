/**
 * Kagenti Phoenix Real-Time Tracing Demo
 *
 * A walkthrough of Phoenix real-time trace analysis:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to Phoenix (page.goto PHOENIX_URL)
 *   3. Show landing page
 *   4. Click Traces tab
 *   5. Wait for traces to load
 *   6. Click first trace for detail view
 *   7. Hover over span details
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 *   PHOENIX_URL      - Phoenix UI URL
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
const PHOENIX_URL = process.env.PHOENIX_URL || '';

test.describe('Phoenix Real-Time Tracing Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Phoenix tracing: landing, traces, trace detail, spans', async ({ page }) => {
    test.setTimeout(180000); // 3 minutes

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

    // ================================================================
    // STEP 3: Navigate to Phoenix
    // ================================================================
    markStep('phoenix_navigate');

    if (PHOENIX_URL) {
      console.log('[demo] Step 3: Navigate to Phoenix');
      await page.goto(PHOENIX_URL, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 4: Show landing page
      // ================================================================
      markStep('phoenix_landing');
      console.log('[demo] Step 4: Show Phoenix landing page');

      // Hover over the main content area to show the landing page
      const mainContent = page.locator('main, [class*="content"], [class*="dashboard"]').first();
      if (await mainContent.isVisible({ timeout: 5000 }).catch(() => false)) {
        const box = await mainContent.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 3);
          await page.waitForTimeout(LONG_PAUSE);
        }
      }
      await page.waitForTimeout(PAUSE);

      // ================================================================
      // STEP 5: Click Traces tab
      // ================================================================
      markStep('phoenix_traces');
      console.log('[demo] Step 5: Click Traces tab');

      const tracesNav = page.getByRole('link', { name: /Traces/i })
        .or(page.locator('a[href*="trace"]'));
      if (await tracesNav.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(tracesNav.first(), 'Phoenix Traces');
        await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(LONG_PAUSE);
      } else {
        console.log('[demo] Phoenix traces nav not found — may already be on traces page');
      }

      // Wait for traces to load
      console.log('[demo] Waiting for traces to load...');
      await page.waitForTimeout(3000);

      // ================================================================
      // STEP 6: Click first trace for detail view
      // ================================================================
      markStep('phoenix_trace_detail');
      console.log('[demo] Step 6: Click first trace for detail');

      const phoenixTraceSelectors = [
        page.locator('table tbody tr').first(),
        page.locator('[role="row"]').nth(1),
        page.locator('[class*="trace"] a, [class*="row"]').first(),
      ];
      let traceClicked = false;
      for (const sel of phoenixTraceSelectors) {
        if (await sel.isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(sel, 'Phoenix trace detail');
          traceClicked = true;
          break;
        }
      }
      if (traceClicked) {
        await page.waitForTimeout(3000);
        console.log('[demo] Showing Phoenix trace detail');
      } else {
        console.log('[demo] No trace rows found');
      }
      await page.waitForTimeout(LONG_PAUSE);

      // ================================================================
      // STEP 7: Hover over span details
      // ================================================================
      markStep('phoenix_spans');
      console.log('[demo] Step 7: Hover over span details');

      // Look for span elements in the trace detail view
      const spanElements = page.locator('[class*="span"], [class*="tree"] [role="treeitem"], [class*="node"], [class*="bar"]');
      const spanCount = await spanElements.count();
      console.log(`[demo] Found ${spanCount} span-like elements`);

      for (let i = 0; i < Math.min(spanCount, 5); i++) {
        const span = spanElements.nth(i);
        if (await span.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await span.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(800);
          }
        }
      }

      // Hover over detail panels (attributes, token counts, latency)
      const detailPanels = page.locator('[class*="detail"], [class*="attributes"], [class*="panel"]');
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

      // Scroll to see more details
      await page.mouse.wheel(0, 300);
      await page.waitForTimeout(PAUSE);

    } else {
      console.log('[demo] Phoenix URL not set, skipping Phoenix sections');
      markStep('phoenix_landing');
      markStep('phoenix_traces');
      markStep('phoenix_trace_detail');
      markStep('phoenix_spans');
    }

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Phoenix real-time tracing demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'phoenix-realtime-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
