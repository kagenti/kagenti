/**
 * Kagenti Tool Integration Demo
 *
 * A walkthrough of tool deployment and agent interaction:
 *   1. Login
 *   2. Navigate to Tool Catalog, show weather-tool details
 *   3. Show MCP Tools tab with tool list
 *   4. Invoke the tool directly from UI
 *   5. Navigate to Agent Catalog, open weather-service
 *   6. Chat with agent (agent uses the tool)
 *   7. Show that traces capture both agent and tool calls
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

test.describe('Tool Integration Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Tool integration: catalog, MCP tools, invoke, agent chat, traces', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes

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
    // STEP 3: Navigate to Tool Catalog
    // ================================================================
    markStep('tool_catalog');
    console.log('[demo] Step 3: Navigate to Tool Catalog');

    const toolsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Tools$/ });
    await demoClick(toolsLink.first(), 'Tools sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Tools/i }).first(), 'Tools link');
    });
    await page.waitForURL('**/tools', { timeout: 10000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Show weather-tool details
    // ================================================================
    markStep('tool_detail');
    console.log('[demo] Step 4: Show weather-tool details');

    const weatherTool = page.locator('a').filter({ hasText: /weather/i })
      .or(page.getByText('weather-tool', { exact: false }))
      .or(page.getByText('weather', { exact: false }));
    if (await weatherTool.first().isVisible({ timeout: 10000 }).catch(() => false)) {
      await demoClick(weatherTool.first(), 'Weather tool');
      await page.waitForURL('**/tools/**/**', { timeout: 10000 }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      console.log(`[demo] Tool detail URL: ${page.url()}`);
    } else {
      console.log('[demo] Weather tool not found in catalog');
    }

    await page.waitForTimeout(LONG_PAUSE);

    // Hover over detail sections
    const detailCards = page.locator('.pf-v5-c-card, [class*="card"], .pf-v5-c-description-list');
    const detailCount = await detailCards.count();
    for (let i = 0; i < Math.min(detailCount, 4); i++) {
      const card = detailCards.nth(i);
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
    // STEP 5: Show MCP Tools tab
    // ================================================================
    markStep('tool_mcp');
    console.log('[demo] Step 5: Show MCP Tools tab');

    const mcpTab = page.getByRole('tab', { name: /MCP|Tools|Endpoints/i })
      .or(page.locator('button:has-text("MCP Tools")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("MCP")'))
      .or(page.locator('li button').filter({ hasText: /MCP|Tools/i }));

    if (await mcpTab.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(mcpTab.first(), 'MCP Tools tab');
      await page.waitForTimeout(LONG_PAUSE);

      // Hover over tool list items
      const toolItems = page.locator('[class*="tool-item"], [class*="list-item"], tr, [role="row"]');
      const itemCount = await toolItems.count();
      for (let i = 0; i < Math.min(itemCount, 5); i++) {
        const item = toolItems.nth(i);
        if (await item.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await item.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    } else {
      console.log('[demo] MCP Tools tab not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Invoke tool directly
    // ================================================================
    markStep('tool_invoke');
    console.log('[demo] Step 6: Invoke tool directly');

    const invokeBtn = page.getByRole('button', { name: /invoke|run|execute|test/i })
      .or(page.locator('button').filter({ hasText: /invoke|run|execute|test/i }));

    if (await invokeBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(invokeBtn.first(), 'Invoke/Run button');
      await page.waitForTimeout(LONG_PAUSE);

      // Look for input form for tool invocation
      const toolInput = page.locator('textarea, input[type="text"]').last();
      if (await toolInput.isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(toolInput, 'Tool input');
        await toolInput.fill('{"location": "New York"}');
        await page.waitForTimeout(PAUSE);

        const runBtn = page.getByRole('button', { name: /send|run|invoke|submit/i });
        if (await runBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(runBtn.first(), 'Run tool');
          await page.waitForTimeout(LONG_PAUSE);
        }
      }
    } else {
      console.log('[demo] Invoke button not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Navigate to Agent Catalog and open weather-service
    // ================================================================
    markStep('agent_navigate');
    console.log('[demo] Step 7: Navigate to Agent Catalog');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });
    await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    const weatherAgent = page.locator('a').filter({ hasText: 'weather-service' })
      .or(page.getByText('weather-service'));
    if (await weatherAgent.first().isVisible({ timeout: 10000 }).catch(() => false)) {
      await demoClick(weatherAgent.first(), 'weather-service agent');
      await page.waitForURL('**/agents/**/**', { timeout: 10000 }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    } else {
      console.log('[demo] weather-service agent not found');
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 8: Chat with agent
    // ================================================================
    markStep('agent_chat');
    console.log('[demo] Step 8: Chat with agent');

    const chatTab = page.getByRole('tab', { name: /Chat/i })
      .or(page.locator('button:has-text("Chat")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Chat")'))
      .or(page.locator('li button').filter({ hasText: /Chat/i }));

    if (await chatTab.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(chatTab.first(), 'Chat tab');
      await page.waitForTimeout(LONG_PAUSE);

      const chatInput = page.locator('textarea, input[type="text"]').filter({ has: page.locator('[placeholder*="message" i], [placeholder*="chat" i], [placeholder*="ask" i]') })
        .or(page.locator('textarea').last())
        .or(page.locator('input[placeholder*="message" i]'));

      if (await chatInput.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(chatInput.first(), 'Chat input');
        await chatInput.first().fill('What is the weather in San Francisco?');
        await page.waitForTimeout(PAUSE);

        const sendBtn = page.getByRole('button', { name: /send/i })
          .or(page.locator('button[type="submit"]'))
          .or(page.locator('button:has(svg)').last());
        if (await sendBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(sendBtn.first(), 'Send button');
        } else {
          await page.keyboard.press('Enter');
        }
        console.log('[demo] Sent chat query to agent');
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 9: Wait for response and show traces
    // ================================================================
    markStep('agent_response');
    console.log('[demo] Step 9: Wait for response');

    let responseElapsed = 0;
    const maxResponseWait = 30000;

    while (responseElapsed < maxResponseWait) {
      const responseMessages = page.locator('[class*="message"]').or(page.locator('[class*="response"]'));
      const msgCount = await responseMessages.count();
      if (msgCount > 1) {
        console.log('[demo] Chat response received');
        const lastMsg = responseMessages.last();
        if (await lastMsg.isVisible({ timeout: 2000 }).catch(() => false)) {
          await lastMsg.scrollIntoViewIfNeeded().catch(() => {});
          const box = await lastMsg.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(LONG_PAUSE);
          }
        }
        break;
      }
      await page.waitForTimeout(3000);
      responseElapsed += 3000;
    }

    // Navigate to observability to show traces
    const obsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /Observability/i })
      .or(page.getByRole('link', { name: /Observability/i }));
    if (await obsLink.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(obsLink.first(), 'Observability sidebar link');
      await page.waitForTimeout(LONG_PAUSE);

      // Hover over trace entries
      const traceRows = page.locator('tr, [role="row"], [class*="trace"]');
      const traceCount = await traceRows.count();
      for (let i = 0; i < Math.min(traceCount, 5); i++) {
        const row = traceRows.nth(i);
        if (await row.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await row.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Tool integration demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'tool-integration-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
