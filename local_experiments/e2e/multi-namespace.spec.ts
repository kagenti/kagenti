/**
 * Kagenti Multi-Namespace Management Demo
 *
 * A walkthrough of multi-namespace management:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to Agent Catalog
 *   3. Select team1 namespace, show agents
 *   4. Switch to team2 namespace, show empty/different agents
 *   5. Switch back to team1
 *   6. Navigate to Tool Catalog, show namespace switching there too
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

test.describe('Multi-Namespace Management Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Multi-namespace: team1, team2, agents, tools', async ({ page }) => {
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

    // Helper: select a namespace from the namespace dropdown
    const selectNamespace = async (nsName: string) => {
      const nsSelector = page.locator('[aria-label="Select namespace"]')
        .or(page.getByRole('button', { name: /Select namespace|namespace/i }))
        .or(page.locator('button').filter({ hasText: /team1|team2|namespace/i }));

      if (await nsSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
        await demoClick(nsSelector.first(), `Namespace selector (selecting ${nsName})`);
        await page.waitForTimeout(500);

        const nsOption = page.getByText(nsName, { exact: true })
          .or(page.locator('[role="option"]').filter({ hasText: nsName }));
        if (await nsOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(nsOption.first(), `${nsName} namespace`);
          console.log(`[demo] Selected ${nsName} namespace`);
          await page.waitForTimeout(PAUSE);
          return true;
        }
      }
      console.log(`[demo] Could not select namespace ${nsName}`);
      return false;
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
    // STEP 3: Navigate to Agent Catalog and select team1
    // ================================================================
    markStep('agents_team1');
    console.log('[demo] Step 3: Navigate to Agent Catalog, select team1');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });

    await expect(page).toHaveURL(/\/agents/, { timeout: 10000 });
    await page.waitForTimeout(PAUSE);

    // Select team1 namespace
    await selectNamespace('team1');
    await page.waitForTimeout(LONG_PAUSE);

    // Show the agents in team1
    const team1Agents = page.locator('table tbody tr, [role="row"]');
    const team1Count = await team1Agents.count();
    console.log(`[demo] team1 has ${team1Count} agent rows`);

    for (let i = 0; i < Math.min(team1Count, 4); i++) {
      const row = team1Agents.nth(i);
      if (await row.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await row.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 4: Switch to team2 namespace
    // ================================================================
    markStep('agents_team2');
    console.log('[demo] Step 4: Switch to team2 namespace');

    await selectNamespace('team2');
    await page.waitForTimeout(LONG_PAUSE);

    // Show the agents (or empty state) in team2
    const team2Agents = page.locator('table tbody tr, [role="row"]');
    const team2Count = await team2Agents.count();
    console.log(`[demo] team2 has ${team2Count} agent rows`);

    if (team2Count > 0) {
      for (let i = 0; i < Math.min(team2Count, 4); i++) {
        const row = team2Agents.nth(i);
        if (await row.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await row.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    } else {
      // Show empty state
      const emptyState = page.locator('[class*="empty"], [class*="Empty"]')
        .or(page.getByText(/no agents|no items|empty/i));
      if (await emptyState.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        const box = await emptyState.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Switch back to team1
    // ================================================================
    markStep('agents_switch_back');
    console.log('[demo] Step 5: Switch back to team1');

    await selectNamespace('team1');
    await page.waitForTimeout(LONG_PAUSE);

    // Verify team1 agents are showing again
    const team1AgentsAgain = page.locator('table tbody tr, [role="row"]');
    const team1CountAgain = await team1AgentsAgain.count();
    console.log(`[demo] team1 again has ${team1CountAgain} agent rows`);
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Navigate to Tool Catalog, show team1 tools
    // ================================================================
    markStep('tools_team1');
    console.log('[demo] Step 6: Navigate to Tool Catalog, team1');

    const toolsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Tools$/ });
    await demoClick(toolsLink.first(), 'Tools sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Tools/i }).first(), 'Tools link');
    });

    await expect(page).toHaveURL(/\/tools/, { timeout: 10000 });
    await page.waitForTimeout(PAUSE);

    // Select team1 namespace in Tool Catalog
    await selectNamespace('team1');
    await page.waitForTimeout(LONG_PAUSE);

    // Hover over tools in team1
    const team1Tools = page.locator('table tbody tr, [role="row"]');
    const toolCount1 = await team1Tools.count();
    console.log(`[demo] team1 has ${toolCount1} tool rows`);

    for (let i = 0; i < Math.min(toolCount1, 4); i++) {
      const row = team1Tools.nth(i);
      if (await row.isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await row.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Switch to team2 in Tool Catalog
    // ================================================================
    markStep('tools_team2');
    console.log('[demo] Step 7: Switch to team2 in Tool Catalog');

    await selectNamespace('team2');
    await page.waitForTimeout(LONG_PAUSE);

    // Show team2 tools
    const team2Tools = page.locator('table tbody tr, [role="row"]');
    const toolCount2 = await team2Tools.count();
    console.log(`[demo] team2 has ${toolCount2} tool rows`);

    if (toolCount2 > 0) {
      for (let i = 0; i < Math.min(toolCount2, 4); i++) {
        const row = team2Tools.nth(i);
        if (await row.isVisible({ timeout: 2000 }).catch(() => false)) {
          const box = await row.boundingBox();
          if (box) {
            await humanMove(box.x + box.width / 2, box.y + box.height / 2);
            await page.waitForTimeout(600);
          }
        }
      }
    } else {
      const emptyState = page.locator('[class*="empty"], [class*="Empty"]')
        .or(page.getByText(/no tools|no items|empty/i));
      if (await emptyState.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        const box = await emptyState.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
      }
    }
    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Multi-namespace management demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'multi-namespace-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
