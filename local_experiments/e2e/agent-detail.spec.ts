/**
 * Kagenti Agent Detail Page Demo
 *
 * A deep dive into the agent detail page:
 *   1. Login and navigate to Agent Catalog
 *   2. Open weather-service agent
 *   3. Show Overview tab (status, replicas, service info)
 *   4. Show Specs tab (YAML view, copy button)
 *   5. Show Logs/Events tab
 *   6. Show agent card info
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

test.describe('Agent Detail Page Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Agent detail: overview, specs, events, agent card', async ({ page }) => {
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
    // STEP 3: Navigate to Agent Catalog
    // ================================================================
    markStep('agent_catalog');
    console.log('[demo] Step 3: Navigate to Agent Catalog');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });

    await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
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
        console.log('[demo] Selected team1 namespace');
        await page.waitForTimeout(PAUSE);
      }
    }
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Open weather-service agent
    // ================================================================
    console.log('[demo] Step 4: Open weather-service agent');

    const weatherAgent = page.locator('a').filter({ hasText: 'weather-service' })
      .or(page.getByText('weather-service'));
    if (await weatherAgent.first().isVisible({ timeout: 20000 }).catch(() => false)) {
      await demoClick(weatherAgent.first(), 'weather-service agent');
      await page.waitForURL('**/agents/**/**', { timeout: 10000 }).catch(() => {});
      console.log(`[demo] Agent detail URL: ${page.url()}`);
    } else {
      console.log('[demo] weather-service not found in catalog');
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Show Overview tab
    // ================================================================
    markStep('agent_overview');
    console.log('[demo] Step 5: Show Overview tab');

    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Click Overview tab if not already active
    const overviewTab = page.getByRole('tab', { name: /Overview/i })
      .or(page.locator('button:has-text("Overview")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Overview")'))
      .or(page.locator('li button').filter({ hasText: /Overview/i }));
    if (await overviewTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(overviewTab.first(), 'Overview tab');
      await page.waitForTimeout(PAUSE);
    }

    // Hover over status, replicas, and service info sections
    const detailCards = page.locator('.pf-v5-c-card, [class*="card"], .pf-v5-c-description-list');
    const detailCount = await detailCards.count();
    console.log(`[demo] Found ${detailCount} detail sections on overview`);

    for (let i = 0; i < Math.min(detailCount, 6); i++) {
      const card = detailCards.nth(i);
      if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await card.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }

    // Scroll down to see all overview content
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 6: Show Specs tab (YAML view)
    // ================================================================
    markStep('agent_specs');
    console.log('[demo] Step 6: Show Specs tab');

    // Scroll back to top for tab clicking
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

      // Scroll through the YAML content
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);

      // Look for copy button and hover over it
      const copyButton = page.locator('button:has-text("Copy")')
        .or(page.locator('[aria-label*="copy" i]'))
        .or(page.locator('button:has(svg)').filter({ has: page.locator('[data-icon="copy"]') }));
      if (await copyButton.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        const box = await copyButton.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(PAUSE);
        }
        console.log('[demo] Copy button highlighted');
      }

      // Scroll through more YAML
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      // Try finding specs by index
      const allTabs = page.locator('[role="tab"]');
      const tabCount = await allTabs.count();
      console.log(`[demo] Specs tab not found by name, checking ${tabCount} tabs`);
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent() || '';
        console.log(`[demo]   Tab ${i}: "${tabText.trim()}"`);
        if (tabText.toLowerCase().includes('spec') || tabText.toLowerCase().includes('yaml')) {
          await allTabs.nth(i).click();
          await page.waitForTimeout(LONG_PAUSE);
          break;
        }
      }
    }

    // ================================================================
    // STEP 7: Show Logs/Events tab
    // ================================================================
    markStep('agent_events');
    console.log('[demo] Step 7: Show Logs/Events tab');

    // Scroll back to top for tab clicking
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(500);

    const eventsTab = page.getByRole('tab', { name: /Events|Logs|Log/i })
      .or(page.locator('button:has-text("Events")'))
      .or(page.locator('button:has-text("Logs")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Events")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Logs")'))
      .or(page.locator('li button').filter({ hasText: /Events|Logs/i }));

    if (await eventsTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(eventsTab.first(), 'Events/Logs tab');
      await page.waitForTimeout(LONG_PAUSE);

      // Scroll through logs/events content
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      // Try finding events/logs by tab index
      const allTabs = page.locator('[role="tab"]');
      const tabCount = await allTabs.count();
      console.log(`[demo] Events tab not found by name, checking ${tabCount} tabs`);
      for (let i = 0; i < tabCount; i++) {
        const tabText = await allTabs.nth(i).textContent() || '';
        if (tabText.toLowerCase().includes('event') || tabText.toLowerCase().includes('log')) {
          await allTabs.nth(i).click();
          await page.waitForTimeout(LONG_PAUSE);
          break;
        }
      }
    }

    // ================================================================
    // STEP 8: Show agent card info
    // ================================================================
    markStep('agent_card');
    console.log('[demo] Step 8: Show agent card info');

    // Scroll back to top
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(500);

    // Look for Agent Card tab or section
    const agentCardTab = page.getByRole('tab', { name: /Agent Card|Card/i })
      .or(page.locator('button:has-text("Agent Card")'))
      .or(page.locator('.pf-v5-c-tabs__link:has-text("Agent Card")'))
      .or(page.locator('li button').filter({ hasText: /Agent Card|Card/i }));

    if (await agentCardTab.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(agentCardTab.first(), 'Agent Card tab');
      await page.waitForTimeout(LONG_PAUSE);

      // Scroll through agent card content
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      // Agent card info might be on the Overview tab — switch back
      console.log('[demo] No Agent Card tab, checking Overview for card info');
      if (await overviewTab.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(overviewTab.first(), 'Back to Overview');
        await page.waitForTimeout(PAUSE);
      }

      // Look for agent card section within the page
      const agentCardSection = page.locator('[class*="agent-card"]')
        .or(page.getByText('Agent Card', { exact: false }))
        .or(page.getByText('/.well-known/agent-card.json'));
      if (await agentCardSection.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await agentCardSection.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await agentCardSection.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      } else {
        console.log('[demo] Agent card section not found');
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Agent detail demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'agent-detail-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
