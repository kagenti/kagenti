/**
 * Kagenti End-to-End Deployment Lifecycle Demo
 *
 * A full lifecycle walkthrough:
 *   1. Login
 *   2. Import agent with weather-service example
 *   3. Submit and watch build progress
 *   4. Wait for agent to become ready
 *   5. Navigate to agent detail
 *   6. Open Chat tab and send a query
 *   7. Wait for response
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

test.describe('End-to-End Deployment Lifecycle Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('E2E deploy: import, build, ready, chat', async ({ page }) => {
    test.setTimeout(600000); // 10 minutes

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
    // STEP 3: Navigate to Import Agent and fill form
    // ================================================================
    markStep('e2e_import');
    console.log('[demo] Step 3: Navigate to Import Agent and fill form');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });
    await expect(page).toHaveURL(/\/agents/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    const importBtn = page.getByRole('button', { name: /Import/i })
      .or(page.getByRole('link', { name: /Import/i }))
      .or(page.locator('a[href*="import"]'));
    // ASSERT: Import button must be visible
    await expect(importBtn.first()).toBeVisible({ timeout: 5000 });
    await demoClick(importBtn.first(), 'Import Agent button');

    await expect(page).toHaveURL(/\/import/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Try selecting weather-service example
    const examplesDropdown = page.locator('select[name*="example" i]')
      .or(page.getByRole('button', { name: /example|template|select example/i }))
      .or(page.locator('[aria-label*="example" i]'))
      .or(page.locator('button').filter({ hasText: /example|template/i }));

    if (await examplesDropdown.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(examplesDropdown.first(), 'Examples dropdown');
      await page.waitForTimeout(500);
      const weatherOption = page.getByText('weather-service', { exact: false })
        .or(page.locator('[role="option"]').filter({ hasText: 'weather-service' }));
      if (await weatherOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(weatherOption.first(), 'weather-service example');
        await page.waitForTimeout(PAUSE);
      } else {
        await page.keyboard.press('Escape');
      }
    }

    // Fill agent name
    const nameField = page.locator('input[name="name"], input[id="name"], #agent-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Agent name field');
      await nameField.first().clear();
      await nameField.first().fill('e2e-demo');
      await page.waitForTimeout(500);
    }

    // Select namespace
    const nsSelector = page.locator('[aria-label="Select namespace"]')
      .or(page.locator('select[name="namespace"]'))
      .or(page.getByRole('button', { name: /Select namespace|namespace/i }));
    if (await nsSelector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(nsSelector.first(), 'Namespace selector');
      await page.waitForTimeout(500);
      const team1Option = page.getByText('team1', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'team1' }));
      if (await team1Option.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(team1Option.first(), 'team1 namespace');
        await page.waitForTimeout(500);
      }
    }

    // Fill path if not auto-filled
    const pathField = page.locator('input[name*="path" i]')
      .or(page.locator('input[placeholder*="path" i]'));
    if (await pathField.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      const pathValue = await pathField.first().inputValue();
      if (!pathValue) {
        await demoClick(pathField.first(), 'Path field');
        await pathField.first().fill('weather-service');
        await page.waitForTimeout(500);
      }
    }

    // Select build strategy
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);

    const buildStrategySelector = page.locator('select[name*="build" i][name*="strategy" i]')
      .or(page.getByRole('button', { name: /build strategy|buildah|kaniko|strategy/i }))
      .or(page.locator('[aria-label*="build strategy" i]'))
      .or(page.locator('[aria-label*="strategy" i]'))
      .or(page.locator('button').filter({ hasText: /buildah|kaniko|strategy/i }));

    if (await buildStrategySelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(buildStrategySelector.first(), 'Build strategy selector');
      await page.waitForTimeout(500);

      const buildahOption = page.getByText('buildah', { exact: false })
        .or(page.locator('[role="option"]').filter({ hasText: /buildah/i }));
      if (await buildahOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(buildahOption.first(), 'buildah strategy');
        await page.waitForTimeout(500);
      } else {
        const firstOption = page.locator('[role="option"]').first()
          .or(page.locator('[role="menuitem"]').first());
        if (await firstOption.isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(firstOption, 'First available build strategy');
          await page.waitForTimeout(500);
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 4: Submit the form
    // ================================================================
    markStep('e2e_submit');
    console.log('[demo] Step 4: Submit the import form');

    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);

    const submitFormBtn = page.getByRole('button', { name: /^Import$|^Submit$|^Create$|^Deploy$/i })
      .or(page.locator('button[type="submit"]'));
    if (await submitFormBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(submitFormBtn.first(), 'Submit/Import button');
      await page.waitForTimeout(LONG_PAUSE);
    }

    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] Post-submit URL: ${page.url()}`);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Watch build progress
    // ================================================================
    markStep('e2e_building');
    console.log('[demo] Step 5: Watching build progress');

    await injectCursor();

    // Poll for build completion (up to 5 minutes)
    const maxBuildWait = 300000;
    const pollInterval = 10000;
    let elapsed = 0;
    let buildComplete = false;

    while (elapsed < maxBuildWait) {
      const successIndicator = page.getByText(/Succeeded|Complete|Ready|Built/i);
      const failIndicator = page.getByText(/Failed|Error/i);

      if (await successIndicator.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        console.log('[demo] Build succeeded!');
        buildComplete = true;
        break;
      }

      if (await failIndicator.first().isVisible({ timeout: 1000 }).catch(() => false)) {
        console.log('[demo] Build failed');
        break;
      }

      // Show current build phase
      const phaseIndicator = page.locator('[class*="phase"]')
        .or(page.locator('[class*="status"]'))
        .or(page.getByText(/Building|Pending|Running/i));
      if (await phaseIndicator.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await phaseIndicator.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        }
      }

      console.log(`[demo] Build in progress... (${elapsed / 1000}s)`);
      await page.waitForTimeout(pollInterval);
      elapsed += pollInterval;

      await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Wait for agent to become ready
    // ================================================================
    markStep('e2e_ready');
    console.log('[demo] Step 6: Wait for agent to become ready');

    if (buildComplete) {
      // Navigate to agents catalog to check agent status
      const agentsNav = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
      await demoClick(agentsNav.first(), 'Agents sidebar link').catch(async () => {
        await page.goto(`${UI_URL}/agents`, { waitUntil: 'networkidle', timeout: 15000 });
        await injectCursor();
      });
      await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(PAUSE);

      // Poll for agent ready state
      let readyElapsed = 0;
      const maxReadyWait = 120000;

      while (readyElapsed < maxReadyWait) {
        const readyAgent = page.locator('a, [class*="card"]').filter({ hasText: 'e2e-demo' });
        if (await readyAgent.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          console.log('[demo] Agent e2e-demo found in catalog');
          break;
        }
        console.log(`[demo] Waiting for agent to appear... (${readyElapsed / 1000}s)`);
        await page.waitForTimeout(10000);
        readyElapsed += 10000;
        await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
        await injectCursor();
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Navigate to agent detail
    // ================================================================
    markStep('e2e_detail');
    console.log('[demo] Step 7: Navigate to agent detail');

    const agentLink = page.locator('a').filter({ hasText: 'e2e-demo' })
      .or(page.getByText('e2e-demo'));
    if (await agentLink.first().isVisible({ timeout: 10000 }).catch(() => false)) {
      await demoClick(agentLink.first(), 'e2e-demo agent');
      await page.waitForURL('**/agents/**/**', { timeout: 10000 }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      console.log(`[demo] Agent detail URL: ${page.url()}`);
    } else {
      console.log('[demo] e2e-demo agent not found in catalog');
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 8: Open Chat tab and send query
    // ================================================================
    markStep('e2e_chat');
    console.log('[demo] Step 8: Open Chat tab');

    const chatTab = page.getByRole('tab', { name: /Chat/i })
      .or(page.locator('button:has-text("Chat")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Chat")'))
      .or(page.locator('li button').filter({ hasText: /Chat/i }));

    // ASSERT: Chat tab must be visible on the agent detail page
    await expect(chatTab.first()).toBeVisible({ timeout: 5000 });
    await demoClick(chatTab.first(), 'Chat tab');
    await page.waitForTimeout(LONG_PAUSE);

    // Find chat input and send a query
    const chatInput = page.locator('textarea, input[type="text"]').filter({ has: page.locator('[placeholder*="message" i], [placeholder*="chat" i], [placeholder*="ask" i]') })
      .or(page.locator('textarea').last())
      .or(page.locator('input[placeholder*="message" i]'));

    if (await chatInput.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(chatInput.first(), 'Chat input');
      await chatInput.first().fill('What is the weather in New York?');
      await page.waitForTimeout(PAUSE);

      // Send the message
      const sendBtn = page.getByRole('button', { name: /send/i })
        .or(page.locator('button[type="submit"]'))
        .or(page.locator('button:has(svg)').last());
      if (await sendBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(sendBtn.first(), 'Send button');
      } else {
        await page.keyboard.press('Enter');
      }
      console.log('[demo] Sent chat query');
      await page.waitForTimeout(LONG_PAUSE);
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 9: Wait for response
    // ================================================================
    markStep('e2e_response');
    console.log('[demo] Step 9: Wait for chat response');

    // Wait for a response to appear
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

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] End-to-end deployment lifecycle demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'e2e-deploy-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
