/**
 * Kagenti Tool Detail and MCP Invocation Demo
 *
 * A walkthrough of the tool detail page and MCP tools:
 *   1. Login and navigate to Tool Catalog
 *   2. Open weather-tool
 *   3. Show Overview tab
 *   4. Show MCP Tools tab (list available tools with schemas)
 *   5. Invoke a tool (click invoke, fill params if possible)
 *   6. Show Specs tab
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

test.describe('Tool Detail and MCP Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Tool detail: overview, MCP tools, invoke, specs', async ({ page }) => {
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
    // STEP 3: Navigate to Tool Catalog (via sidebar — SPA routing)
    // ================================================================
    markStep('tool_catalog');
    console.log('[demo] Step 3: Navigate to Tool Catalog');

    const toolsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Tools$/ });
    await demoClick(toolsLink.first(), 'Tools sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Tools/i }).first(), 'Tools link');
    });

    await page.waitForURL('**/tools', { timeout: 10000 }).catch(() => {});
    console.log(`[demo] Tool catalog URL: ${page.url()}`);
    await page.waitForTimeout(PAUSE);

    // Select team1 namespace if needed
    const nsSelector = page.locator('[aria-label="Select namespace"]')
      .or(page.getByRole('button', { name: /team1|Select namespace|namespace/i }));
    if (await nsSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await nsSelector.first().click();
      await page.waitForTimeout(500);
      const team1Option = page.getByText('team1', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'team1' }));
      if (await team1Option.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await team1Option.first().click();
        console.log('[demo] Selected team1 namespace');
        await page.waitForTimeout(PAUSE);
      }
    }
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Open weather-tool
    // ================================================================
    console.log('[demo] Step 4: Open weather-tool');

    const weatherTool = page.locator('a').filter({ hasText: 'weather-tool' })
      .or(page.getByText('weather-tool'));
    if (await weatherTool.first().isVisible({ timeout: 20000 }).catch(() => false)) {
      await demoClick(weatherTool.first(), 'weather-tool');
      await page.waitForURL('**/tools/**/**', { timeout: 10000 }).catch(() => {});
      console.log(`[demo] Tool detail URL: ${page.url()}`);
    } else {
      // Try any tool that's visible
      const anyTool = page.locator('a[href*="/tools/"]').first();
      if (await anyTool.isVisible({ timeout: 5000 }).catch(() => false)) {
        const toolName = await anyTool.textContent();
        console.log(`[demo] weather-tool not found, opening: ${toolName?.trim()}`);
        await demoClick(anyTool, `Tool: ${toolName?.trim()}`);
        await page.waitForURL('**/tools/**/**', { timeout: 10000 }).catch(() => {});
      } else {
        console.log('[demo] No tools found in catalog');
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Show Overview tab
    // ================================================================
    markStep('tool_overview');
    console.log('[demo] Step 5: Show Tool Overview tab');

    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Click Overview tab if available
    const overviewTab = page.getByRole('tab', { name: /Overview/i })
      .or(page.locator('button:has-text("Overview")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Overview")'))
      .or(page.locator('li button').filter({ hasText: /Overview/i }));
    if (await overviewTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(overviewTab.first(), 'Overview tab');
      await page.waitForTimeout(PAUSE);
    }

    // Hover over tool detail sections
    const toolCards = page.locator('.pf-v5-c-card, [class*="card"], .pf-v5-c-description-list');
    const cardCount = await toolCards.count();
    console.log(`[demo] Found ${cardCount} detail sections`);

    for (let i = 0; i < Math.min(cardCount, 4); i++) {
      const card = toolCards.nth(i);
      if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await card.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Show MCP Tools tab
    // ================================================================
    markStep('tool_mcp_list');
    console.log('[demo] Step 6: Show MCP Tools tab');

    // Scroll to top for tab access
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(500);

    const mcpTab = page.getByRole('tab', { name: /MCP Tools|Tools|MCP/i })
      .or(page.locator('button:has-text("MCP Tools")'))
      .or(page.locator('button:has-text("Tools")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("MCP Tools")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Tools")'))
      .or(page.locator('li button').filter({ hasText: /MCP Tools|Tools/i }));

    if (await mcpTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(mcpTab.first(), 'MCP Tools tab');
      await page.waitForTimeout(LONG_PAUSE);

      // Hover over MCP tool list items to show schemas
      const toolItems = page.locator('[class*="tool-item"], [class*="tool-list"] li, table tbody tr, .pf-v5-c-data-list__item');
      const toolItemCount = await toolItems.count();
      console.log(`[demo] Found ${toolItemCount} MCP tool items`);

      for (let i = 0; i < Math.min(toolItemCount, 5); i++) {
        const item = toolItems.nth(i);
        if (await item.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await item.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(800);
          }
        }
      }

      // Scroll through tool list
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      // Try finding by tab index
      const allTabs = page.locator('[role="tab"]');
      const tabCount = await allTabs.count();
      console.log(`[demo] MCP tab not found by name, checking ${tabCount} tabs`);
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent() || '';
        console.log(`[demo]   Tab ${i}: "${tabText.trim()}"`);
        if (tabText.toLowerCase().includes('mcp') || tabText.toLowerCase().includes('tool')) {
          await allTabs.nth(i).click();
          await page.waitForTimeout(LONG_PAUSE);
          break;
        }
      }
    }

    // ================================================================
    // STEP 7: Invoke a tool
    // ================================================================
    markStep('tool_invoke');
    console.log('[demo] Step 7: Invoke a tool');

    // Look for an Invoke/Run/Try button
    const invokeButton = page.locator('button:has-text("Invoke")')
      .or(page.locator('button:has-text("Run")'))
      .or(page.locator('button:has-text("Try")'))
      .or(page.locator('button:has-text("Execute")'))
      .or(page.locator('[aria-label*="invoke" i]'))
      .or(page.locator('[aria-label*="run" i]'));

    if (await invokeButton.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(invokeButton.first(), 'Invoke tool button');
      await page.waitForTimeout(PAUSE);

      // Fill in parameters if a form appears
      const paramInput = page.locator('input[type="text"]')
        .or(page.locator('textarea'))
        .or(page.locator('[placeholder*="param" i]'))
        .or(page.locator('[placeholder*="city" i]'))
        .or(page.locator('[placeholder*="location" i]'));

      if (await paramInput.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await paramInput.first().fill('San Francisco');
        console.log('[demo] Filled parameter: San Francisco');
        await page.waitForTimeout(PAUSE);

        // Submit the invocation
        const submitInvoke = page.locator('button:has-text("Submit")')
          .or(page.locator('button:has-text("Send")')
          .or(page.locator('button:has-text("Run")')
          .or(page.locator('button[type="submit"]'))));
        if (await submitInvoke.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(submitInvoke.first(), 'Submit invocation');
          await page.waitForTimeout(LONG_PAUSE);

          // Wait for response
          console.log('[demo] Waiting for tool invocation response...');
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] No parameter input found after invoke click');
        await page.waitForTimeout(PAUSE);
      }
    } else {
      // Try clicking on a specific tool row to expand/invoke
      const toolRow = page.locator('table tbody tr, .pf-v5-c-data-list__item').first();
      if (await toolRow.isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(toolRow, 'First tool row');
        await page.waitForTimeout(LONG_PAUSE);

        // Check if invoke button appeared after expanding
        if (await invokeButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(invokeButton.first(), 'Invoke tool button');
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] No invoke button or tool rows found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Show Specs tab
    // ================================================================
    markStep('tool_specs');
    console.log('[demo] Step 8: Show Tool Specs tab');

    // Scroll to top for tab access
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(500);

    const specsTab = page.getByRole('tab', { name: /Specs|Spec|YAML/i })
      .or(page.locator('button:has-text("Specs")'))
      .or(page.locator('button:has-text("Spec")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Spec")'))
      .or(page.locator('li button').filter({ hasText: /Spec/i }));

    if (await specsTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(specsTab.first(), 'Specs tab');
      await page.waitForTimeout(LONG_PAUSE);

      // Scroll through YAML content
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      const allTabs = page.locator('[role="tab"]');
      const tabCount = await allTabs.count();
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent() || '';
        if (tabText.toLowerCase().includes('spec') || tabText.toLowerCase().includes('yaml')) {
          await allTabs.nth(i).click();
          await page.waitForTimeout(LONG_PAUSE);
          break;
        }
      }
    }

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Tool detail MCP demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'tool-detail-mcp-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
