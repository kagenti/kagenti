/**
 * Kagenti Import Agent Form Walkthrough Demo
 *
 * A walkthrough of the full Import Agent form:
 *   1. Login and navigate to Agents > Import Agent
 *   2. Select example from dropdown if available
 *   3. Fill name, namespace fields
 *   4. Show git URL, path, branch fields
 *   5. Show framework selector (LangGraph, CrewAI, etc.)
 *   6. Show protocol selector (A2A, MCP)
 *   7. Show deployment method toggle
 *   8. Show registry selector
 *   9. Show workload type selector
 *   10. Do NOT submit the form
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

test.describe('Import Agent Form Walkthrough Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Import agent: examples, fields, framework, protocol, deploy method', async ({ page }) => {
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
    // STEP 3: Navigate to Import Agent page
    // ================================================================
    markStep('import_navigate');
    console.log('[demo] Step 3: Navigate to Import Agent page');

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
    console.log(`[demo] Import page URL: ${page.url()}`);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Select example from dropdown
    // ================================================================
    markStep('import_examples');
    console.log('[demo] Step 4: Select example from dropdown');

    const examplesDropdown = page.locator('select[name*="example" i]')
      .or(page.getByRole('button', { name: /example|template|select example/i }))
      .or(page.locator('[aria-label*="example" i]'))
      .or(page.locator('button').filter({ hasText: /example|template/i }));

    if (await examplesDropdown.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(examplesDropdown.first(), 'Examples dropdown');
      await page.waitForTimeout(PAUSE);

      const weatherOption = page.getByText('weather-service', { exact: false })
        .or(page.locator('[role="option"]').filter({ hasText: 'weather-service' }))
        .or(page.locator('[role="menuitem"]').filter({ hasText: 'weather-service' }));
      if (await weatherOption.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(weatherOption.first(), 'weather-service example');
        await page.waitForTimeout(PAUSE);
        console.log('[demo] Selected weather-service example');
      } else {
        // Close dropdown if weather-service not found
        await page.keyboard.press('Escape');
        console.log('[demo] weather-service example not found in dropdown');
      }
    } else {
      console.log('[demo] Examples dropdown not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Fill name and namespace
    // ================================================================
    markStep('import_name');
    console.log('[demo] Step 5: Fill name and namespace');

    const nameField = page.locator('input[name="name"], input[id="name"], #agent-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Agent name field');
      await nameField.first().clear();
      await nameField.first().fill('demo-agent-test');
      await page.waitForTimeout(500);
      console.log('[demo] Filled agent name: demo-agent-test');
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
    // STEP 6: Show git URL, path, branch fields
    // ================================================================
    markStep('import_source');
    console.log('[demo] Step 6: Show git source fields');

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

    const branchField = page.locator('input[name*="branch" i]')
      .or(page.locator('input[name*="ref" i]'))
      .or(page.locator('input[placeholder*="branch" i]'))
      .or(page.locator('input[placeholder*="main" i]'));
    if (await branchField.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await branchField.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await branchField.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted branch field');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Show framework selector
    // ================================================================
    markStep('import_framework');
    console.log('[demo] Step 7: Show framework selector');

    const frameworkSelector = page.locator('select[name*="framework" i]')
      .or(page.getByRole('button', { name: /framework|select framework/i }))
      .or(page.locator('[aria-label*="framework" i]'))
      .or(page.locator('button').filter({ hasText: /framework/i }));

    if (await frameworkSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await frameworkSelector.first().scrollIntoViewIfNeeded().catch(() => {});
      await demoClick(frameworkSelector.first(), 'Framework selector');
      await page.waitForTimeout(PAUSE);

      // Click through framework options
      const frameworks = ['LangGraph', 'CrewAI', 'AG2', 'Custom'];
      for (const fw of frameworks) {
        const fwOption = page.getByText(fw, { exact: true })
          .or(page.locator('[role="option"]').filter({ hasText: fw }))
          .or(page.locator('[role="menuitem"]').filter({ hasText: fw }));
        if (await fwOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(fwOption.first(), `${fw} framework`);
          await page.waitForTimeout(800);
          // Re-open dropdown for next option
          if (fw !== frameworks[frameworks.length - 1]) {
            if (await frameworkSelector.first().isVisible({ timeout: 2000 }).catch(() => false)) {
              await demoClick(frameworkSelector.first(), 'Framework selector (re-open)');
              await page.waitForTimeout(500);
            }
          }
          console.log(`[demo] Clicked framework: ${fw}`);
        }
      }
    } else {
      console.log('[demo] Framework selector not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Show protocol selector
    // ================================================================
    markStep('import_protocol');
    console.log('[demo] Step 8: Show protocol selector');

    const protocolSelector = page.locator('select[name*="protocol" i]')
      .or(page.getByRole('button', { name: /protocol|select protocol/i }))
      .or(page.locator('[aria-label*="protocol" i]'))
      .or(page.locator('button').filter({ hasText: /protocol/i }));

    if (await protocolSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await protocolSelector.first().scrollIntoViewIfNeeded().catch(() => {});
      await demoClick(protocolSelector.first(), 'Protocol selector');
      await page.waitForTimeout(PAUSE);

      // Show A2A option
      const a2aOption = page.getByText('A2A', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'A2A' }))
        .or(page.locator('[role="menuitem"]').filter({ hasText: 'A2A' }));
      if (await a2aOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(a2aOption.first(), 'A2A protocol');
        await page.waitForTimeout(800);
        console.log('[demo] Selected A2A protocol');
      }

      // Re-open and show MCP option
      if (await protocolSelector.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        await demoClick(protocolSelector.first(), 'Protocol selector (re-open)');
        await page.waitForTimeout(500);
        const mcpOption = page.getByText('MCP', { exact: true })
          .or(page.locator('[role="option"]').filter({ hasText: 'MCP' }))
          .or(page.locator('[role="menuitem"]').filter({ hasText: 'MCP' }));
        if (await mcpOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(mcpOption.first(), 'MCP protocol');
          await page.waitForTimeout(800);
          console.log('[demo] Selected MCP protocol');
        }
      }
    } else {
      console.log('[demo] Protocol selector not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 9: Show deployment method toggle
    // ================================================================
    markStep('import_deploy_method');
    console.log('[demo] Step 9: Show deployment method toggle');

    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);

    const deployToggle = page.locator('[aria-label*="deploy" i]')
      .or(page.locator('input[type="radio"][name*="deploy" i]'))
      .or(page.locator('button').filter({ hasText: /build from source|pre-built|deploy method/i }))
      .or(page.locator('label').filter({ hasText: /build from source|pre-built/i }))
      .or(page.locator('[class*="toggle"]').filter({ hasText: /build|deploy/i }));

    if (await deployToggle.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await deployToggle.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await deployToggle.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      await demoClick(deployToggle.first(), 'Deployment method toggle');
      await page.waitForTimeout(PAUSE);
      console.log('[demo] Toggled deployment method');
    } else {
      console.log('[demo] Deployment method toggle not found');
    }

    // Show registry selector
    const registrySelector = page.locator('select[name*="registry" i]')
      .or(page.getByRole('button', { name: /registry|select registry/i }))
      .or(page.locator('[aria-label*="registry" i]'))
      .or(page.locator('input[name*="registry" i]'))
      .or(page.locator('input[placeholder*="registry" i]'));

    if (await registrySelector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
      await registrySelector.first().scrollIntoViewIfNeeded().catch(() => {});
      const box = await registrySelector.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }
      console.log('[demo] Highlighted registry selector');
    } else {
      console.log('[demo] Registry selector not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 10: Show workload type selector
    // ================================================================
    markStep('import_workload');
    console.log('[demo] Step 10: Show workload type selector');

    const workloadSelector = page.locator('select[name*="workload" i]')
      .or(page.getByRole('button', { name: /workload|deployment|statefulset/i }))
      .or(page.locator('[aria-label*="workload" i]'))
      .or(page.locator('button').filter({ hasText: /workload type|Deployment|StatefulSet/i }));

    if (await workloadSelector.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await workloadSelector.first().scrollIntoViewIfNeeded().catch(() => {});
      await demoClick(workloadSelector.first(), 'Workload type selector');
      await page.waitForTimeout(PAUSE);

      const deploymentOption = page.getByText('Deployment', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'Deployment' }));
      if (await deploymentOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await deploymentOption.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }

      const statefulsetOption = page.getByText('StatefulSet', { exact: true })
        .or(page.locator('[role="option"]').filter({ hasText: 'StatefulSet' }));
      if (await statefulsetOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
        const box = await statefulsetOption.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(800);
        }
      }

      // Close dropdown
      await page.keyboard.press('Escape');
    } else {
      console.log('[demo] Workload type selector not found');
    }

    await page.waitForTimeout(PAUSE);

    // Scroll back up to show the full form
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Import agent form walkthrough complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'agent-import-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
