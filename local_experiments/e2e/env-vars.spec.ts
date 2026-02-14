/**
 * Kagenti Environment Variable Management Demo
 *
 * A walkthrough of the Import Agent environment variable management:
 *   1. Login to Kagenti via Keycloak
 *   2. Navigate to Import Agent page
 *   3. Fill basic fields (name, namespace)
 *   4. Scroll to env vars section
 *   5. Click Add Variable, show direct value entry
 *   6. Click Add Variable again, show ConfigMap ref dropdown
 *   7. Click Add Variable, show Secret ref dropdown
 *   8. Show Import from File button (just hover, don't actually import)
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

test.describe('Environment Variable Management Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Env vars: direct value, ConfigMap ref, Secret ref, import file', async ({ page }) => {
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
    await demoLogin(page, demoClick);

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 3: Navigate to Import Agent page (via sidebar — SPA routing)
    // ================================================================
    markStep('import_navigate');
    console.log('[demo] Step 3: Navigate to Import Agent page');

    // Navigate to Agents page first, then click Import button
    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });
    await expect(page).toHaveURL(/\/agents/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Click Import Agent button on the agents page
    const importBtn = page.getByRole('button', { name: /Import/i })
      .or(page.getByRole('link', { name: /Import/i }))
      .or(page.locator('a[href*="import"]'));
    // ASSERT: Import button must be visible
    await expect(importBtn.first()).toBeVisible({ timeout: 5000 });
    await demoClick(importBtn.first(), 'Import Agent button');

    await expect(page).toHaveURL(/\/import/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] Import page URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Fill basic fields (name, namespace)
    // ================================================================
    markStep('import_basic');
    console.log('[demo] Step 4: Fill basic agent fields');

    // Fill agent name
    const nameField = page.locator('input[name="name"], input[id="name"], #agent-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Agent name field');
      await nameField.first().fill('demo-agent');
      await page.waitForTimeout(500);
      console.log('[demo] Filled agent name: demo-agent');
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

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Scroll to env vars section, add direct value
    // ================================================================
    markStep('env_direct');
    console.log('[demo] Step 5: Scroll to env vars, add direct value');

    // Scroll down to find env vars section
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(PAUSE);

    // Look for Environment Variables section heading
    const envSection = page.getByText('Environment Variables', { exact: false })
      .or(page.locator('[class*="env"]'))
      .or(page.getByText('Env Vars', { exact: false }));
    if (await envSection.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await envSection.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await envSection.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
    }

    // Click Add Variable button
    const addVarBtn = page.getByRole('button', { name: /Add Variable|Add Env|Add/i })
      .or(page.locator('button:has-text("Add Variable")'))
      .or(page.locator('button:has-text("Add")').filter({ hasText: /var|env/i }));
    if (await addVarBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(addVarBtn.first(), 'Add Variable button');
      await page.waitForTimeout(PAUSE);

      // Fill in a direct value environment variable
      const envNameInputs = page.locator('input[placeholder*="name" i], input[name*="env"][name*="name" i]');
      const envNameCount = await envNameInputs.count();
      if (envNameCount > 0) {
        const lastEnvName = envNameInputs.last();
        await demoClick(lastEnvName, 'Env var name field');
        await lastEnvName.fill('API_KEY');
        await page.waitForTimeout(500);
      }

      const envValueInputs = page.locator('input[placeholder*="value" i], input[name*="env"][name*="value" i]');
      const envValueCount = await envValueInputs.count();
      if (envValueCount > 0) {
        const lastEnvValue = envValueInputs.last();
        await demoClick(lastEnvValue, 'Env var value field');
        await lastEnvValue.fill('sk-demo-key-12345');
        await page.waitForTimeout(500);
      }
      console.log('[demo] Added direct value env var: API_KEY');
    } else {
      console.log('[demo] Add Variable button not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Add ConfigMap ref
    // ================================================================
    markStep('env_configmap');
    console.log('[demo] Step 6: Add ConfigMap ref env var');

    // Click Add Variable again
    if (await addVarBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(addVarBtn.first(), 'Add Variable (ConfigMap)');
      await page.waitForTimeout(PAUSE);

      // Fill env var name
      const envNameInputs = page.locator('input[placeholder*="name" i], input[name*="env"][name*="name" i]');
      const envNameCount = await envNameInputs.count();
      if (envNameCount > 0) {
        const lastEnvName = envNameInputs.last();
        await demoClick(lastEnvName, 'Env var name field');
        await lastEnvName.fill('DATABASE_URL');
        await page.waitForTimeout(500);
      }

      // Look for source type selector (ConfigMap/Secret/Direct)
      const sourceSelector = page.locator('select[name*="source" i], select[name*="type" i]')
        .or(page.locator('button').filter({ hasText: /Direct|ConfigMap|Source/i }))
        .or(page.locator('[aria-label*="source" i]'));
      if (await sourceSelector.last().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(sourceSelector.last(), 'Source type selector');
        await page.waitForTimeout(500);

        const configMapOption = page.getByText('ConfigMap', { exact: true })
          .or(page.locator('[role="option"]').filter({ hasText: 'ConfigMap' }))
          .or(page.locator('option:has-text("ConfigMap")'));
        if (await configMapOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(configMapOption.first(), 'ConfigMap option');
          await page.waitForTimeout(PAUSE);
          console.log('[demo] Selected ConfigMap source type');
        }
      } else {
        console.log('[demo] Source type selector not found');
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Add Secret ref
    // ================================================================
    markStep('env_secret');
    console.log('[demo] Step 7: Add Secret ref env var');

    // Click Add Variable again
    if (await addVarBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(addVarBtn.first(), 'Add Variable (Secret)');
      await page.waitForTimeout(PAUSE);

      // Fill env var name
      const envNameInputs = page.locator('input[placeholder*="name" i], input[name*="env"][name*="name" i]');
      const envNameCount = await envNameInputs.count();
      if (envNameCount > 0) {
        const lastEnvName = envNameInputs.last();
        await demoClick(lastEnvName, 'Env var name field');
        await lastEnvName.fill('SECRET_TOKEN');
        await page.waitForTimeout(500);
      }

      // Select Secret source type
      const sourceSelector = page.locator('select[name*="source" i], select[name*="type" i]')
        .or(page.locator('button').filter({ hasText: /Direct|ConfigMap|Secret|Source/i }))
        .or(page.locator('[aria-label*="source" i]'));
      if (await sourceSelector.last().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(sourceSelector.last(), 'Source type selector');
        await page.waitForTimeout(500);

        const secretOption = page.getByText('Secret', { exact: true })
          .or(page.locator('[role="option"]').filter({ hasText: 'Secret' }))
          .or(page.locator('option:has-text("Secret")'));
        if (await secretOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
          await demoClick(secretOption.first(), 'Secret option');
          await page.waitForTimeout(PAUSE);
          console.log('[demo] Selected Secret source type');
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Show Import from File button (just hover)
    // ================================================================
    markStep('env_import');
    console.log('[demo] Step 8: Show Import from File button');

    // Look for Import from File button
    const importFileBtn = page.getByRole('button', { name: /Import from File|Import File|Upload/i })
      .or(page.locator('button:has-text("Import")').filter({ hasText: /file/i }))
      .or(page.locator('button:has-text("Upload")'))
      .or(page.locator('input[type="file"]'));

    if (await importFileBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await importFileBtn.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await importFileBtn.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
        console.log('[demo] Hovering over Import from File button');
      }
    } else {
      console.log('[demo] Import from File button not found');
      // Scroll down to look for it
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    }

    await page.waitForTimeout(PAUSE);

    // Scroll back up to show the full form with all env vars
    await page.mouse.wheel(0, -300);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Environment variable management demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'env-vars-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
