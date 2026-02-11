/**
 * Kagenti Agent Build Progress Demo
 *
 * A walkthrough of the agent build lifecycle:
 *   1. Login and navigate to Import Agent
 *   2. Fill and submit: name, namespace, git source, build strategy
 *   3. Wait for redirect to build progress page
 *   4. Show build phase indicator
 *   5. Show build metadata
 *   6. Show events panel
 *   7. Wait for build to complete or show progress
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

test.describe('Agent Build Progress Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Agent build: import, submit, build progress, events', async ({ page }) => {
    test.setTimeout(300000); // 5 minutes (builds take time)

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
    // STEP 3: Navigate to Import Agent and fill form
    // ================================================================
    markStep('build_import');
    console.log('[demo] Step 3: Navigate to Import Agent and fill form');

    const agentsLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsLink.first(), 'Agents sidebar link').catch(async () => {
      await demoClick(page.getByRole('link', { name: /Agents/i }).first(), 'Agents link');
    });
    await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    const importBtn = page.getByRole('button', { name: /Import/i })
      .or(page.getByRole('link', { name: /Import/i }))
      .or(page.locator('a[href*="import"]'));
    if (await importBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(importBtn.first(), 'Import Agent button');
    }

    await page.waitForURL('**/import**', { timeout: 10000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Fill agent name
    const nameField = page.locator('input[name="name"], input[id="name"], #agent-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Agent name field');
      await nameField.first().fill('build-demo');
      await page.waitForTimeout(500);
      console.log('[demo] Filled agent name: build-demo');
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

    // Fill path field with weather-service
    const pathField = page.locator('input[name*="path" i]')
      .or(page.locator('input[placeholder*="path" i]'));
    if (await pathField.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoClick(pathField.first(), 'Path field');
      await pathField.first().fill('weather-service');
      await page.waitForTimeout(500);
      console.log('[demo] Filled path: weather-service');
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
        .or(page.locator('[role="option"]').filter({ hasText: /buildah/i }))
        .or(page.locator('[role="menuitem"]').filter({ hasText: /buildah/i }));
      if (await buildahOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(buildahOption.first(), 'buildah strategy');
        await page.waitForTimeout(500);
        console.log('[demo] Selected buildah build strategy');
      } else {
        // Select first available strategy
        const firstOption = page.locator('[role="option"]').first()
          .or(page.locator('[role="menuitem"]').first());
        if (await firstOption.isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(firstOption, 'First available build strategy');
          await page.waitForTimeout(500);
        }
      }
    } else {
      console.log('[demo] Build strategy selector not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 4: Submit the form
    // ================================================================
    markStep('build_submit');
    console.log('[demo] Step 4: Submit the import form');

    // Scroll to find the submit button
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);

    const submitBtn = page.getByRole('button', { name: /^Import$|^Submit$|^Create$|^Deploy$/i })
      .or(page.locator('button[type="submit"]'));
    if (await submitBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(submitBtn.first(), 'Submit/Import button');
      await page.waitForTimeout(LONG_PAUSE);
      console.log('[demo] Form submitted');
    } else {
      console.log('[demo] Submit button not found');
    }

    // Wait for navigation to build progress page
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    console.log(`[demo] Post-submit URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 5: Show build progress
    // ================================================================
    markStep('build_progress');
    console.log('[demo] Step 5: Show build phase indicator');

    await injectCursor();

    // Look for build phase / status indicator
    const phaseIndicator = page.locator('[class*="phase"]')
      .or(page.locator('[class*="status"]'))
      .or(page.locator('[class*="progress"]'))
      .or(page.getByText(/Building|Pending|Running|Succeeded|Failed/i));

    if (await phaseIndicator.first().isVisible({ timeout: 15000 }).catch(() => false)) {
      await phaseIndicator.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await phaseIndicator.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(LONG_PAUSE);
      }
      console.log('[demo] Build phase indicator visible');
    } else {
      console.log('[demo] Build phase indicator not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Show build metadata
    // ================================================================
    markStep('build_metadata');
    console.log('[demo] Step 6: Show build metadata');

    const metadataCards = page.locator('.pf-v5-c-card, [class*="card"], .pf-v5-c-description-list')
      .or(page.locator('[class*="metadata"]'))
      .or(page.locator('[class*="detail"]'));
    const metaCount = await metadataCards.count();
    console.log(`[demo] Found ${metaCount} metadata sections`);

    for (let i = 0; i < Math.min(metaCount, 4); i++) {
      const card = metadataCards.nth(i);
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
    // STEP 7: Show events panel
    // ================================================================
    markStep('build_events');
    console.log('[demo] Step 7: Show events panel');

    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);

    const eventsSection = page.getByText('Events', { exact: false })
      .or(page.locator('[class*="events"]'))
      .or(page.locator('[class*="log"]'))
      .or(page.getByRole('tab', { name: /Events|Logs/i }));

    if (await eventsSection.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await eventsSection.first().scrollIntoViewIfNeeded().catch(() => {});
      await demoClick(eventsSection.first(), 'Events section');
      await page.waitForTimeout(LONG_PAUSE);

      // Scroll through events
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(PAUSE);
    } else {
      console.log('[demo] Events section not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Wait for build status update
    // ================================================================
    markStep('build_status');
    console.log('[demo] Step 8: Monitoring build status');

    // Poll for build completion (up to 2 minutes)
    const maxWait = 120000;
    const pollInterval = 5000;
    let elapsed = 0;

    while (elapsed < maxWait) {
      const successIndicator = page.getByText(/Succeeded|Complete|Ready|Built/i);
      const failIndicator = page.getByText(/Failed|Error/i);

      if (await successIndicator.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        console.log('[demo] Build succeeded!');
        await successIndicator.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await successIndicator.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
        break;
      }

      if (await failIndicator.first().isVisible({ timeout: 1000 }).catch(() => false)) {
        console.log('[demo] Build failed');
        break;
      }

      console.log(`[demo] Build in progress... (${elapsed / 1000}s)`);
      await page.waitForTimeout(pollInterval);
      elapsed += pollInterval;

      // Refresh to check for updates
      await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Agent build progress demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'agent-build-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
