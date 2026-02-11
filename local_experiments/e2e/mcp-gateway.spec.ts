/**
 * Kagenti MCP Gateway Page Demo
 *
 * A walkthrough of the MCP Gateway page:
 *   1. Login and navigate to MCP Gateway (sidebar)
 *   2. Show gateway status card
 *   3. Show gateway metrics card
 *   4. Show MCP Inspector link
 *   5. Hover over each card
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

test.describe('MCP Gateway Page Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('MCP Gateway: status, metrics, inspector', async ({ page }) => {
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

    // ASSERT: We're on the Kagenti UI (not stuck on Keycloak)
    expect(page.url()).not.toContain('/realms/');

    // ================================================================
    // STEP 3: Navigate to MCP Gateway
    // ================================================================
    markStep('gateway_navigate');
    console.log('[demo] Step 3: Navigate to MCP Gateway');

    const mcpGatewayLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /MCP Gateway/i })
      .or(page.getByRole('link', { name: /MCP Gateway/i }))
      .or(page.locator('a[href*="mcp-gateway"]'))
      .or(page.locator('a[href*="gateway"]').filter({ hasText: /MCP/i }));

    if (await mcpGatewayLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(mcpGatewayLink.first(), 'MCP Gateway sidebar link');
    } else {
      // Try expanding Gateway section in sidebar first
      const gatewaySection = page.locator('nav button, [role="navigation"] button').filter({ hasText: /Gateway/i });
      if (await gatewaySection.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(gatewaySection.first(), 'Gateway section expander');
        await page.waitForTimeout(500);

        const mcpLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /MCP Gateway/i })
          .or(page.getByRole('link', { name: /MCP Gateway/i }));
        if (await mcpLink.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(mcpLink.first(), 'MCP Gateway link');
        }
      }
    }

    await expect(page).toHaveURL(/\/(?:mcp-)?gateway/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] MCP Gateway URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Show gateway status card
    // ================================================================
    markStep('gateway_status');
    console.log('[demo] Step 4: Show gateway status card');

    const statusCard = page.locator('.pf-v5-c-card').filter({ hasText: /status|health|running/i })
      .or(page.locator('[class*="card"]').filter({ hasText: /status|health|running/i }))
      .or(page.locator('.pf-v5-c-card').first());

    if (await statusCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await statusCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await statusCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }
      console.log('[demo] Hovering over gateway status card');
    } else {
      console.log('[demo] Gateway status card not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Show gateway metrics card
    // ================================================================
    markStep('gateway_metrics');
    console.log('[demo] Step 5: Show gateway metrics card');

    const metricsCard = page.locator('.pf-v5-c-card').filter({ hasText: /metrics|requests|connections|traffic/i })
      .or(page.locator('[class*="card"]').filter({ hasText: /metrics|requests|connections/i }));

    if (await metricsCard.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await metricsCard.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await metricsCard.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }
      console.log('[demo] Hovering over gateway metrics card');
    } else {
      console.log('[demo] Gateway metrics card not found, hovering over available cards');
      // Hover over all visible cards
      const allCards = page.locator('.pf-v5-c-card, [class*="card"]');
      const cardCount = await allCards.count();
      for (let i = 0; i < Math.min(cardCount, 4); i++) {
        const card = allCards.nth(i);
        if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await card.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(800);
          }
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Show MCP Inspector link
    // ================================================================
    markStep('gateway_inspector');
    console.log('[demo] Step 6: Show MCP Inspector link');

    const inspectorLink = page.getByRole('link', { name: /Inspector/i })
      .or(page.locator('a[href*="inspector"]'))
      .or(page.getByText('MCP Inspector', { exact: false }))
      .or(page.locator('button').filter({ hasText: /Inspector/i }));

    if (await inspectorLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await inspectorLink.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await inspectorLink.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }
      console.log('[demo] Hovering over MCP Inspector link');
    } else {
      console.log('[demo] MCP Inspector link not found');
    }

    // Final hover sweep across all cards
    await page.mouse.wheel(0, -300);
    await page.waitForTimeout(500);

    const allCards = page.locator('.pf-v5-c-card, [class*="card"]');
    const cardCount = await allCards.count();
    for (let i = 0; i < Math.min(cardCount, 6); i++) {
      const card = allCards.nth(i);
      if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await card.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] MCP Gateway demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'mcp-gateway-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
