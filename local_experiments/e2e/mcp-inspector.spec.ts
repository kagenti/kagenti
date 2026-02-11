/**
 * Kagenti MCP Inspector Tool Testing Demo
 *
 * A walkthrough of the MCP Inspector tool:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to MCP Gateway page (sidebar)
 *   3. Click MCP Inspector link
 *   4. In Inspector: show tool list, click a tool, hover over schema
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 *   (Inspector URL discovered from gateway page)
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

test.describe('MCP Inspector Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('MCP Inspector: gateway, tools list, tool detail, schema', async ({ page }) => {
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
    // STEP 3: Navigate to MCP Gateway page (via sidebar — SPA routing)
    // ================================================================
    markStep('mcp_gateway_page');
    console.log('[demo] Step 3: Navigate to MCP Gateway page');

    // Look for MCP Gateway or Tools link in sidebar
    const mcpLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /MCP Gateway|MCP|Gateway/i });
    await demoClick(mcpLink.first(), 'MCP Gateway sidebar link').catch(async () => {
      // Try alternative sidebar navigation
      const toolsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /Tools/i });
      await demoClick(toolsLink.first(), 'Tools sidebar link').catch(() => {
        console.log('[demo] MCP Gateway sidebar link not found');
      });
    });

    await page.waitForURL('**/mcp**', { timeout: 10000 }).catch(() => {
      console.log('[demo] MCP Gateway URL pattern not matched');
    });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] MCP Gateway URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // Hover over gateway page content
    const gatewayContent = page.locator('main, [class*="content"]').first();
    if (await gatewayContent.isVisible({ timeout: 3000 }).catch(() => false)) {
      const box = await gatewayContent.boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 3);
        await page.waitForTimeout(PAUSE);
      }
    }

    // ================================================================
    // STEP 4: Click MCP Inspector link
    // ================================================================
    markStep('mcp_inspector_navigate');
    console.log('[demo] Step 4: Click MCP Inspector link');

    // Look for Inspector link on the gateway page
    const inspectorLink = page.locator('a').filter({ hasText: /Inspector|MCP Inspector/i })
      .or(page.locator('a[href*="inspector"]'))
      .or(page.locator('button').filter({ hasText: /Inspector/i }));

    if (await inspectorLink.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      // Get the href before clicking (for page.goto after)
      const inspectorHref = await inspectorLink.first().getAttribute('href').catch(() => '');
      console.log(`[demo] Inspector link href: ${inspectorHref}`);

      await demoClick(inspectorLink.first(), 'MCP Inspector link');

      // Inspector may open in same tab or we need to navigate
      await page.waitForTimeout(3000);
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await injectCursor();
      console.log(`[demo] Inspector URL: ${page.url()}`);
    } else {
      console.log('[demo] MCP Inspector link not found on gateway page');
      // Try navigating to common Inspector paths
      const inspectorPaths = ['/inspector', '/mcp-inspector', '/mcp/inspector'];
      for (const path of inspectorPaths) {
        try {
          const inspectorUrl = new URL(path, UI_URL).toString();
          await page.goto(inspectorUrl, { waitUntil: 'networkidle', timeout: 10000 });
          await injectCursor();
          console.log(`[demo] Tried Inspector at: ${inspectorUrl}`);
          break;
        } catch {
          continue;
        }
      }
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 5: Show tool list in Inspector
    // ================================================================
    markStep('mcp_inspector_tools');
    console.log('[demo] Step 5: Show tool list in Inspector');

    // Look for tool list elements
    const toolItems = page.locator('[class*="tool"], [class*="item"], [role="listitem"], li').filter({ hasText: /.+/ });
    const toolCount = await toolItems.count();
    console.log(`[demo] Found ${toolCount} tool-like items`);

    // Hover over the first few tools
    for (let i = 0; i < Math.min(toolCount, 5); i++) {
      const tool = toolItems.nth(i);
      if (await tool.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await tool.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // Click on first tool to see its detail
    const clickableTools = page.locator('a, button, [role="button"], [class*="clickable"]')
      .filter({ hasText: /tool|function|get|create|list/i });
    if (await clickableTools.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(clickableTools.first(), 'First tool in list');
      await page.waitForTimeout(LONG_PAUSE);
    }

    // ================================================================
    // STEP 6: Show tool detail and hover over schema
    // ================================================================
    markStep('mcp_inspector_detail');
    console.log('[demo] Step 6: Show tool detail and schema');

    // Hover over tool schema/parameters
    const schemaElements = page.locator('[class*="schema"], [class*="param"], [class*="property"], pre, code');
    const schemaCount = await schemaElements.count();
    console.log(`[demo] Found ${schemaCount} schema-like elements`);

    for (let i = 0; i < Math.min(schemaCount, 4); i++) {
      const schema = schemaElements.nth(i);
      if (await schema.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await schema.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }

    // Scroll to see more schema content
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] MCP Inspector demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'mcp-inspector-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
