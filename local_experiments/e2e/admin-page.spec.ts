/**
 * Kagenti Admin Page Demo
 *
 * A walkthrough of the Administration page:
 *   1. Login and navigate to Admin page
 *   2. Show session info card
 *   3. Show auth config card
 *   4. Show Keycloak console link card
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

test.describe('Admin Page Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Admin page: session, auth config, Keycloak console', async ({ page }) => {
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
    // STEP 3: Navigate to Admin page (via sidebar — SPA routing)
    // ================================================================
    console.log('[demo] Step 3: Navigate to Admin page');

    // Expand Operations group in sidebar if collapsed
    const opsGroup = page.locator('nav button, [role="navigation"] button').filter({ hasText: /Operations/i });
    if (await opsGroup.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      const isExpanded = await opsGroup.first().getAttribute('aria-expanded');
      if (isExpanded === 'false') {
        await demoClick(opsGroup.first(), 'Operations group');
        await page.waitForTimeout(500);
      }
    }

    const adminLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /Admin|Administration/i });
    await demoClick(adminLink.first(), 'Admin sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Admin/i }).first(), 'Admin link');
    });

    await page.waitForURL('**/admin', { timeout: 10000 }).catch(() => {});
    console.log(`[demo] Admin URL: ${page.url()}`);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Show session info card
    // ================================================================
    markStep('admin_session');
    console.log('[demo] Step 4: Show session info card');

    // Find session info card (may contain user, roles, token info)
    const sessionCard = page.locator('.pf-v5-c-card, [class*="card"]').filter({ hasText: /Session|User|Token|Identity/i });

    if (await sessionCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await sessionCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await sessionCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Hover over details within the card
      const cardDetails = sessionCard.first().locator('dd, .pf-v5-c-description-list__description, span, p');
      const detailCount = await cardDetails.count();
      for (let i = 0; i < Math.min(detailCount, 5); i++) {
        const detail = cardDetails.nth(i);
        if (await detail.isVisible({ timeout: 1000 }).catch(() => false)) {
          const detailBox = await detail.boundingBox();
          if (detailBox) {
            await humanMove(detailBox.x + detailBox.width / 2, detailBox.y + detailBox.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    } else {
      // Try finding by the first card on the page
      const firstCard = page.locator('.pf-v5-c-card, [class*="card"]').first();
      if (await firstCard.isVisible({ timeout: 3000 }).catch(() => false)) {
        const box = await firstCard.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Session info card not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Show auth config card
    // ================================================================
    markStep('admin_auth');
    console.log('[demo] Step 5: Show auth config card');

    const authCard = page.locator('.pf-v5-c-card, [class*="card"]').filter({ hasText: /Auth|OAuth|OIDC|Config/i });

    if (await authCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await authCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await authCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Hover over auth details
      const authDetails = authCard.first().locator('dd, .pf-v5-c-description-list__description, span, p, code');
      const authDetailCount = await authDetails.count();
      for (let i = 0; i < Math.min(authDetailCount, 5); i++) {
        const detail = authDetails.nth(i);
        if (await detail.isVisible({ timeout: 1000 }).catch(() => false)) {
          const detailBox = await detail.boundingBox();
          if (detailBox) {
            await humanMove(detailBox.x + detailBox.width / 2, detailBox.y + detailBox.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    } else {
      // Try the second card on the page
      const secondCard = page.locator('.pf-v5-c-card, [class*="card"]').nth(1);
      if (await secondCard.isVisible({ timeout: 3000 }).catch(() => false)) {
        const box = await secondCard.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Auth config card not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // Scroll down to see more content
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Show Keycloak console link card
    // ================================================================
    markStep('admin_keycloak');
    console.log('[demo] Step 6: Show Keycloak console link card');

    const keycloakCard = page.locator('.pf-v5-c-card, [class*="card"]').filter({ hasText: /Keycloak/i });

    if (await keycloakCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await keycloakCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await keycloakCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }

      // Hover over the Keycloak console link
      const kcLink = keycloakCard.first().locator('a');
      if (await kcLink.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        const linkBox = await kcLink.first().boundingBox();
        if (linkBox) {
          await humanMove(linkBox.x + linkBox.width / 2, linkBox.y + linkBox.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      }
    } else {
      // Look for Keycloak link anywhere on the page
      const kcLink = page.locator('a[href*="keycloak"]')
        .or(page.getByText('Keycloak Console'))
        .or(page.getByText('Keycloak Admin'));
      if (await kcLink.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await kcLink.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await kcLink.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Keycloak console link not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // Scroll through remaining admin content
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Admin page demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'admin-page-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
