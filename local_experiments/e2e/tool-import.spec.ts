/**
 * Kagenti Import Tool Form Walkthrough Demo
 *
 * A walkthrough of the Import Tool form:
 *   1. Login and navigate to Tools > Import Tool
 *   2. Fill name, namespace fields
 *   3. Show git URL, path fields
 *   4. Show persistent storage config (StatefulSet options)
 *   5. Show port configuration
 *   6. Do NOT submit the form
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

test.describe('Import Tool Form Walkthrough Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Import tool: name, source, storage, ports', async ({ page }) => {
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
    // STEP 3: Navigate to Tools > Import Tool
    // ================================================================
    markStep('tool_import_navigate');
    console.log('[demo] Step 3: Navigate to Import Tool page');

    const toolsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Tools$/ });
    await demoClick(toolsLink.first(), 'Tools sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Tools/i }).first(), 'Tools link');
    });
    await expect(page).toHaveURL(/\/tools/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    const importBtn = page.getByRole('button', { name: /Import/i })
      .or(page.getByRole('link', { name: /Import/i }))
      .or(page.locator('a[href*="import"]'));
    // ASSERT: Import button must be visible
    await expect(importBtn.first()).toBeVisible({ timeout: 5000 });
    await demoClick(importBtn.first(), 'Import Tool button');

    await expect(page).toHaveURL(/\/import/, { timeout: 10000 });
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] Import Tool page URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Fill name and namespace
    // ================================================================
    markStep('tool_import_name');
    console.log('[demo] Step 4: Fill tool name and namespace');

    const nameField = page.locator('input[name="name"], input[id="name"], #tool-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Tool name field');
      await nameField.first().fill('demo-tool-test');
      await page.waitForTimeout(500);
      console.log('[demo] Filled tool name: demo-tool-test');
    }

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
    // STEP 5: Show git URL and path fields
    // ================================================================
    markStep('tool_import_source');
    console.log('[demo] Step 5: Show git source fields');

    const gitUrlField = page.locator('input[name*="git" i][name*="url" i]')
      .or(page.locator('input[name*="repo" i]'))
      .or(page.locator('input[placeholder*="git" i]'))
      .or(page.locator('input[placeholder*="https://" i]'));
    if (await gitUrlField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await gitUrlField.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await gitUrlField.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted git URL field');
    }

    const pathField = page.locator('input[name*="path" i]')
      .or(page.locator('input[placeholder*="path" i]'));
    if (await pathField.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await pathField.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await pathField.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted path field');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Show persistent storage config
    // ================================================================
    markStep('tool_import_storage');
    console.log('[demo] Step 6: Show persistent storage config');

    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);

    // Look for storage / StatefulSet / persistent volume section
    const storageSection = page.getByText('Storage', { exact: false })
      .or(page.getByText('Persistent', { exact: false }))
      .or(page.getByText('StatefulSet', { exact: false }))
      .or(page.locator('[class*="storage"]'));

    if (await storageSection.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await storageSection.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await storageSection.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted storage section');
    }

    // Look for workload type selector to show StatefulSet option
    const workloadSelector = page.locator('select[name*="workload" i]')
      .or(page.getByRole('button', { name: /workload|deployment|statefulset/i }))
      .or(page.locator('[aria-label*="workload" i]'))
      .or(page.locator('button').filter({ hasText: /workload type|Deployment|StatefulSet/i }));

    if (await workloadSelector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(workloadSelector.first(), 'Workload type selector');
      await page.waitForTimeout(500);

      const statefulsetOption = page.getByText('StatefulSet', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'StatefulSet' }));
      if (await statefulsetOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(statefulsetOption.first(), 'StatefulSet option');
        await page.waitForTimeout(PAUSE);
        console.log('[demo] Selected StatefulSet workload type');
      } else {
        await page.keyboard.press('Escape');
      }
    }

    // Look for volume size / mount path fields that appear with StatefulSet
    const volumeFields = page.locator('input[name*="volume" i], input[name*="storage" i], input[name*="mount" i], input[placeholder*="Gi" i]');
    const volumeCount = await volumeFields.count();
    for (let i = 0; i < Math.min(volumeCount, 3); i++) {
      const field = volumeFields.nth(i);
      if (await field.isVisible({ timeout: 2000 }).catch(() => false)) {
        await field.scrollIntoViewIfNeeded().catch(() => {});
        const box = await field.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Show port configuration
    // ================================================================
    markStep('tool_import_ports');
    console.log('[demo] Step 7: Show port configuration');

    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);

    const portSection = page.getByText('Port', { exact: false })
      .or(page.locator('[class*="port"]'))
      .or(page.locator('input[name*="port" i]'))
      .or(page.locator('input[placeholder*="port" i]'));

    if (await portSection.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await portSection.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await portSection.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted port configuration');
    }

    // Hover over port input fields
    const portInputs = page.locator('input[name*="port" i], input[type="number"]');
    const portCount = await portInputs.count();
    for (let i = 0; i < Math.min(portCount, 3); i++) {
      const input = portInputs.nth(i);
      if (await input.isVisible({ timeout: 2000 }).catch(() => false)) {
        await input.scrollIntoViewIfNeeded().catch(() => {});
        const box = await input.boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }
    }

    await page.waitForTimeout(PAUSE);

    // Scroll back up to show the full form
    await page.mouse.wheel(0, -600);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Import tool form walkthrough complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'tool-import-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
