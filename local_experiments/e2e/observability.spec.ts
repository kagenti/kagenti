/**
 * Kagenti Observability Dashboard Demo
 *
 * A walkthrough of the Observability page:
 *   1. Login and navigate to Observability page
 *   2. Show Phoenix card
 *   3. Show Kiali card
 *   4. Hover over dashboard links
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
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

test.describe('Observability Dashboard Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Observability: Phoenix, Kiali, dashboard links', async ({ page }) => {
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
    // STEP 3: Navigate to Observability page (via sidebar — SPA routing)
    // ================================================================
    markStep('obs_page');
    console.log('[demo] Step 3: Navigate to Observability page');

    // Expand Operations group in sidebar if collapsed
    const opsGroup = page.locator('nav button, [role="navigation"] button').filter({ hasText: /Operations/i });
    if (await opsGroup.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      const isExpanded = await opsGroup.first().getAttribute('aria-expanded');
      if (isExpanded === 'false') {
        await demoClick(opsGroup.first(), 'Operations group');
        await page.waitForTimeout(500);
      }
    }

    const obsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /Observability/i });
    await demoClick(obsLink.first(), 'Observability sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Observability/i }).first(), 'Observability link');
    });

    await page.waitForURL('**/observability', { timeout: 10000 }).catch(() => {});
    console.log(`[demo] Observability URL: ${page.url()}`);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Show Phoenix card
    // ================================================================
    markStep('obs_phoenix');
    console.log('[demo] Step 4: Show Phoenix card');

    // Find Phoenix card or section
    const phoenixCard = page.locator('.pf-v5-c-card, [class*="card"]').filter({ hasText: /Phoenix/i })
      .or(page.getByText('Phoenix', { exact: false }).locator('..'));

    if (await phoenixCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await phoenixCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await phoenixCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Hover over the Phoenix link/button within the card
      const phoenixLink = phoenixCard.first().locator('a, button').first();
      if (await phoenixLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        const linkBox = await phoenixLink.boundingBox();
        if (linkBox) {
          await humanMove(linkBox.x + linkBox.width / 2, linkBox.y + linkBox.height / 2);
          await page.waitForTimeout(PAUSE);
        }
      }
    } else {
      // Phoenix might be listed as text or in a different layout
      const phoenixText = page.getByText('Phoenix');
      if (await phoenixText.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await phoenixText.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await phoenixText.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Phoenix card/text not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Show Kiali card
    // ================================================================
    markStep('obs_kiali');
    console.log('[demo] Step 5: Show Kiali card');

    const kialiCard = page.locator('.pf-v5-c-card, [class*="card"]').filter({ hasText: /Kiali/i })
      .or(page.getByText('Kiali', { exact: false }).locator('..'));

    if (await kialiCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await kialiCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await kialiCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Hover over the Kiali link/button within the card
      const kialiLink = kialiCard.first().locator('a, button').first();
      if (await kialiLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        const linkBox = await kialiLink.boundingBox();
        if (linkBox) {
          await humanMove(linkBox.x + linkBox.width / 2, linkBox.y + linkBox.height / 2);
          await page.waitForTimeout(PAUSE);
        }
      }
    } else {
      const kialiText = page.getByText('Kiali');
      if (await kialiText.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await kialiText.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await kialiText.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Kiali card/text not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // Hover over all dashboard links on the page
    console.log('[demo] Hovering over all dashboard links');
    const dashboardLinks = page.locator('a[href*="http"], a[target="_blank"]');
    const linkCount = await dashboardLinks.count();
    console.log(`[demo] Found ${linkCount} external dashboard links`);

    for (let i = 0; i < Math.min(linkCount, 6); i++) {
      const link = dashboardLinks.nth(i);
      if (await link.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await link.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // Scroll through the full observability page
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Observability demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'observability-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
