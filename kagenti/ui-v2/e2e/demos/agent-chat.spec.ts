/**
 * Kagenti Agent Chat Conversation Demo
 *
 * A focused walkthrough of the A2A chat interface:
 *   1. Login and navigate to Agent Catalog
 *   2. Open the weather-service agent
 *   3. Switch to Chat tab
 *   4. Send a query and watch streaming response
 *   5. Show A2A events
 *   6. Send a follow-up query (multi-turn conversation)
 *
 * Environment variables (set by run-playwright-demo.sh):
 *   KAGENTI_UI_URL   - Base URL of the Kagenti UI
 *   KEYCLOAK_USER    - Keycloak username
 *   KEYCLOAK_PASS    - Keycloak password
 */
import { test, expect } from '@playwright/test';
import { demoLogin } from './demo-auth';

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

test.describe('Agent Chat Conversation Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Agent chat: query, streaming, events, follow-up', async ({ page }) => {
    test.setTimeout(240000); // 4 minutes

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
    // STEP 2: Login via Keycloak
    // ================================================================
    markStep('login');
    await demoLogin(page, demoClick);

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 3: Navigate to Agent Catalog
    // ================================================================
    markStep('agent_catalog');
    console.log('[demo] Step 3: Navigate to Agent Catalog');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });

    await expect(page).toHaveURL(/\/agents/, { timeout: 10000 });
    await page.waitForTimeout(PAUSE);

    // Select team1 namespace
    const nsSelector = page.locator('[aria-label="Select namespace"]')
      .or(page.getByRole('button', { name: /team1|Select namespace|namespace/i }));
    if (await nsSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await nsSelector.first().click();
      await page.waitForTimeout(500);
      const team1Option = page.getByText('team1', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'team1' }));
      if (await team1Option.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await team1Option.first().click();
        await page.waitForTimeout(PAUSE);
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 4: Open weather-service agent
    // ================================================================
    markStep('agent_detail');
    console.log('[demo] Step 4: Open weather-service agent');

    const weatherAgent = page.getByRole('button', { name: 'weather-service' })
      .or(page.getByText('weather-service', { exact: true }));
    // ASSERT: weather-service agent must be visible
    await expect(weatherAgent.first()).toBeVisible({ timeout: 20000 });
    await demoClick(weatherAgent.first(), 'weather-service agent');
    await expect(page).toHaveURL(/\/agents\/.*\//, { timeout: 10000 });
    await page.waitForTimeout(PAUSE);

    // Show the agent overview briefly
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 5: Open Chat tab
    // ================================================================
    markStep('chat_open');
    console.log('[demo] Step 5: Open Chat tab');

    // ASSERT: Chat tab must be visible (this is the critical section)
    const chatTab = page.getByRole('tab', { name: /Chat/i })
      .or(page.locator('button:has-text("Chat")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Chat")'))
      .or(page.locator('li button').filter({ hasText: /Chat/i }));
    await expect(chatTab.first()).toBeVisible({ timeout: 5000 });
    await demoClick(chatTab.first(), 'Chat tab');
    await page.waitForTimeout(PAUSE);

    // Show the agent card / skills if visible
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Send first query
    // ================================================================
    markStep('chat_query');
    console.log('[demo] Step 6: Send weather query');

    const chatInputSelectors = [
      page.locator('[aria-label="Chat message input"]'),
      page.locator('textarea'),
      page.locator('[placeholder*="message" i]'),
      page.locator('[placeholder*="type" i]'),
    ];

    // ASSERT: Chat input must be available
    let chatInput = null;
    for (const selector of chatInputSelectors) {
      if (await selector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        chatInput = selector.first();
        break;
      }
    }
    expect(chatInput, 'Chat input field should be visible for sending messages').not.toBeNull();

    if (chatInput) {
      // Type message character by character for visual effect
      const message = 'What is the weather in San Francisco?';
      await chatInput.click();
      await page.waitForTimeout(300);
      await chatInput.fill(message);
      await page.waitForTimeout(LONG_PAUSE);

      // Click Send
      const sendButton = page.getByRole('button', { name: /Send/i })
        .or(page.locator('button:has(svg)').last());
      if (await sendButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(sendButton.first(), 'Send button');
        console.log('[demo] Message sent');
      }

      // ================================================================
      // STEP 7: Watch streaming response
      // ================================================================
      markStep('chat_streaming');
      console.log('[demo] Step 7: Waiting for streaming response');

      // Wait for the response to start appearing
      try {
        await page.waitForFunction(
          () => {
            const messages = document.querySelectorAll('[style*="flex-start"] p, [style*="flex-start"] div');
            return messages.length > 0;
          },
          { timeout: 60000 }
        );
        console.log('[demo] Agent responded');
      } catch {
        console.log('[demo] Response wait timed out');
      }

      await page.waitForTimeout(LONG_PAUSE);

      // Scroll to see the full response
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);

      // ================================================================
      // STEP 8: Show A2A events
      // ================================================================
      markStep('chat_events');
      console.log('[demo] Step 8: Show events panel');

      const eventsPanel = page.locator('button:has-text("Events")')
        .or(page.getByText('Events', { exact: true }));
      if (await eventsPanel.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(eventsPanel.first(), 'Events panel');
        await page.waitForTimeout(LONG_PAUSE);

        // Scroll through events
        await page.mouse.wheel(0, 150);
        await page.waitForTimeout(PAUSE);
      } else {
        console.log('[demo] Events panel not visible');
        await page.waitForTimeout(PAUSE);
      }

      // ================================================================
      // STEP 9: Send follow-up query
      // ================================================================
      markStep('chat_followup');
      console.log('[demo] Step 9: Send follow-up query');

      // Find chat input again (may have been re-rendered)
      let followUpInput = null;
      for (const selector of chatInputSelectors) {
        if (await selector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          followUpInput = selector.first();
          break;
        }
      }

      if (followUpInput) {
        const followUp = 'What about Prague? Compare the temperatures.';
        await followUpInput.click();
        await page.waitForTimeout(300);
        await followUpInput.fill(followUp);
        await page.waitForTimeout(PAUSE);

        if (await sendButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(sendButton.first(), 'Send follow-up');
        }

        // Wait for response
        markStep('chat_followup_response');
        try {
          await page.waitForFunction(
            () => {
              // Look for multiple assistant messages
              const messages = document.querySelectorAll('[style*="flex-start"]');
              return messages.length >= 2;
            },
            { timeout: 60000 }
          );
          console.log('[demo] Follow-up response received');
        } catch {
          console.log('[demo] Follow-up response timed out');
        }

        await page.waitForTimeout(LONG_PAUSE);

        // Scroll to see the full follow-up response
        await page.mouse.wheel(0, 300);
        await page.waitForTimeout(LONG_PAUSE);
      }
    } else {
      console.log('[demo] Chat input not found');
    }

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Agent chat demo complete!');

    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'agent-chat-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
