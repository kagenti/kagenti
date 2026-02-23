/**
 * Kagenti Agent Delete Workflow Demo
 *
 * A walkthrough of the agent delete lifecycle:
 *   1. Login
 *   2. Create a temporary agent (delete-demo) from pre-built image
 *   3. Wait for it to appear in catalog
 *   4. Click delete action on delete-demo
 *   5. Show confirmation modal with name input
 *   6. Type the name to confirm
 *   7. Click delete
 *   8. Show agent removed from catalog
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

test.describe('Agent Delete Workflow Demo', () => {
  test.describe.configure({ mode: 'serial' });

  test('Agent delete: create temp, delete with confirmation', async ({ page }) => {
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
    await demoLogin(page, demoClick);

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 3: Create temporary agent via Import
    // ================================================================
    markStep('create_temp_agent');
    console.log('[demo] Step 3: Create temporary agent delete-demo');

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

    // Fill agent name
    const nameField = page.locator('input[name="name"], input[id="name"], #agent-name')
      .or(page.locator('input[placeholder*="name" i]'));
    if (await nameField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(nameField.first(), 'Agent name field');
      await nameField.first().fill('delete-demo');
      await page.waitForTimeout(500);
      console.log('[demo] Filled agent name: delete-demo');
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

    // Look for deployment method toggle to switch to pre-built image
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);

    const prebuiltToggle = page.locator('label').filter({ hasText: /pre-built|container image|existing image/i })
      .or(page.locator('input[type="radio"]').filter({ has: page.locator('~ *:has-text("pre-built")') }))
      .or(page.locator('button').filter({ hasText: /pre-built|container image/i }))
      .or(page.locator('[aria-label*="deploy" i]'));

    if (await prebuiltToggle.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(prebuiltToggle.first(), 'Pre-built image toggle');
      await page.waitForTimeout(PAUSE);
      console.log('[demo] Switched to pre-built image deployment');
    } else {
      console.log('[demo] Pre-built toggle not found, using build from source');
    }

    // Fill image field
    const imageField = page.locator('input[name*="image" i]')
      .or(page.locator('input[placeholder*="image" i]'))
      .or(page.locator('input[placeholder*="quay" i]'))
      .or(page.locator('input[placeholder*="registry" i]'));
    if (await imageField.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(imageField.first(), 'Image field');
      await imageField.first().fill('quay.io/kagenti/weather-service:latest');
      await page.waitForTimeout(500);
      console.log('[demo] Filled image: quay.io/kagenti/weather-service:latest');
    } else {
      // If no image field, fill git path instead (build from source fallback)
      const pathField = page.locator('input[name*="path" i]')
        .or(page.locator('input[placeholder*="path" i]'));
      if (await pathField.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(pathField.first(), 'Path field');
        await pathField.first().fill('weather-service');
        await page.waitForTimeout(500);
      }

      // Select build strategy
      const buildStrategySelector = page.locator('select[name*="build" i][name*="strategy" i]')
        .or(page.getByRole('button', { name: /build strategy|buildah|kaniko|strategy/i }))
        .or(page.locator('[aria-label*="strategy" i]'))
        .or(page.locator('button').filter({ hasText: /buildah|kaniko|strategy/i }));
      if (await buildStrategySelector.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(buildStrategySelector.first(), 'Build strategy selector');
        await page.waitForTimeout(500);
        const buildahOption = page.getByText('buildah', { exact: false })
          .or(page.locator('[role="option"]').first());
        if (await buildahOption.first().isVisible({ timeout: 2000 }).catch(() => false)) {
          await demoClick(buildahOption.first(), 'Build strategy option');
          await page.waitForTimeout(500);
        }
      }
    }

    // Submit the form
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);

    const submitBtn = page.getByRole('button', { name: /^Import$|^Submit$|^Create$|^Deploy$/i })
      .or(page.locator('button[type="submit"]'));
    if (await submitBtn.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(submitBtn.first(), 'Submit/Import button');
      await page.waitForTimeout(LONG_PAUSE);
      console.log('[demo] Agent creation submitted');
    }

    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // STEP 4: Wait for agent to appear in catalog
    // ================================================================
    markStep('agent_created');
    console.log('[demo] Step 4: Wait for agent to appear in catalog');

    await injectCursor();

    // Navigate to agents catalog
    const agentsNav = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
    await demoClick(agentsNav.first(), 'Agents sidebar link').catch(async () => {
      await page.goto(`${UI_URL}/agents`, { waitUntil: 'networkidle', timeout: 15000 });
      await injectCursor();
    });
    await page.waitForURL('**/agents', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(PAUSE);

    // Poll for agent to appear
    let agentFound = false;
    let elapsed = 0;
    const maxWait = 120000;

    while (elapsed < maxWait) {
      const deleteAgent = page.locator('a, [class*="card"], tr, [role="row"]').filter({ hasText: 'delete-demo' });
      if (await deleteAgent.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        console.log('[demo] Agent delete-demo found in catalog');
        agentFound = true;
        await deleteAgent.first().scrollIntoViewIfNeeded().catch(() => {});
        const box = await deleteAgent.first().boundingBox();
        if (box) {
          await humanMove(box.x + box.width / 2, box.y + box.height / 2);
          await page.waitForTimeout(LONG_PAUSE);
        }
        break;
      }
      console.log(`[demo] Waiting for delete-demo to appear... (${elapsed / 1000}s)`);
      await page.waitForTimeout(10000);
      elapsed += 10000;
      await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 5: Navigate to delete action
    // ================================================================
    markStep('delete_navigate');
    console.log('[demo] Step 5: Navigate to delete action');

    // Find the agent row/card and look for kebab menu or delete button
    const agentRow = page.locator('a, [class*="card"], tr, [role="row"]').filter({ hasText: 'delete-demo' });

    if (await agentRow.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      // Look for kebab menu (3-dot actions menu) on the agent row
      const kebabMenu = agentRow.first().locator('button[aria-label*="action" i], button[aria-label*="kebab" i], [class*="kebab"], [class*="actions"]')
        .or(agentRow.first().locator('button').last());

      if (await kebabMenu.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(kebabMenu.first(), 'Actions menu (kebab)');
        await page.waitForTimeout(PAUSE);
      }
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 6: Click delete action
    // ================================================================
    markStep('delete_action');
    console.log('[demo] Step 6: Click delete action');

    const deleteAction = page.getByRole('menuitem', { name: /delete/i })
      .or(page.locator('[role="menuitem"]').filter({ hasText: /delete/i }))
      .or(page.getByRole('button', { name: /delete/i }))
      .or(page.locator('button').filter({ hasText: /^Delete$/i }));

    if (await deleteAction.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await demoClick(deleteAction.first(), 'Delete action');
      await page.waitForTimeout(LONG_PAUSE);
      console.log('[demo] Delete action clicked');
    } else {
      console.log('[demo] Delete action not found in menu');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 7: Show confirmation modal and type name
    // ================================================================
    markStep('delete_confirm');
    console.log('[demo] Step 7: Show delete confirmation modal');

    // Look for confirmation modal
    const modal = page.locator('[role="dialog"], .pf-v5-c-modal-box, [class*="modal"]');
    if (await modal.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      console.log('[demo] Confirmation modal visible');

      // Hover over modal content
      const box = await modal.first().boundingBox();
      if (box) {
        await humanMove(box.x + box.width / 2, box.y + box.height / 2);
        await page.waitForTimeout(PAUSE);
      }

      // Find confirmation input and type the agent name
      const confirmInput = modal.first().locator('input[type="text"]')
        .or(page.locator('[role="dialog"] input'))
        .or(page.locator('.pf-v5-c-modal-box input'));
      if (await confirmInput.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(confirmInput.first(), 'Confirmation name input');
        await confirmInput.first().fill('delete-demo');
        await page.waitForTimeout(PAUSE);
        console.log('[demo] Typed confirmation name: delete-demo');
      }

      // Click delete/confirm button in modal
      const confirmDeleteBtn = modal.first().locator('button').filter({ hasText: /^Delete$|^Confirm$/i })
        .or(page.locator('[role="dialog"] button').filter({ hasText: /delete|confirm/i }));
      if (await confirmDeleteBtn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoClick(confirmDeleteBtn.first(), 'Confirm Delete button');
        await page.waitForTimeout(LONG_PAUSE);
        console.log('[demo] Delete confirmed');
      }
    } else {
      console.log('[demo] Confirmation modal not found');
    }

    await page.waitForTimeout(PAUSE);

    // ================================================================
    // STEP 8: Show agent removed from catalog
    // ================================================================
    markStep('delete_complete');
    console.log('[demo] Step 8: Show agent removed from catalog');

    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await injectCursor();

    // Verify we're back on the agents catalog or refresh it
    if (!page.url().includes('/agents')) {
      const agentsBackLink = page.locator('nav a, [role="navigation"] a').filter({ hasText: /^Agents$/ });
      await demoClick(agentsBackLink.first(), 'Back to Agents catalog').catch(async () => {
        await page.goto(`${UI_URL}/agents`, { waitUntil: 'networkidle', timeout: 15000 });
        await injectCursor();
      });
    }

    await page.waitForTimeout(LONG_PAUSE);

    // Verify the agent is gone
    const deletedAgent = page.locator('a, [class*="card"], tr, [role="row"]').filter({ hasText: 'delete-demo' });
    const isStillVisible = await deletedAgent.first().isVisible({ timeout: 5000 }).catch(() => false);
    if (!isStillVisible) {
      console.log('[demo] Agent delete-demo successfully removed from catalog');
    } else {
      console.log('[demo] Agent delete-demo may still be present (deletion in progress)');
      // Reload and check again
      await page.reload({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {});
      await injectCursor();
      await page.waitForTimeout(LONG_PAUSE);
    }

    // Hover over the catalog to show it's gone
    const catalogCards = page.locator('.pf-v5-c-card, [class*="card"], tr, [role="row"]');
    const cardCount = await catalogCards.count();
    for (let i = 0; i < Math.min(cardCount, 4); i++) {
      const card = catalogCards.nth(i);
      if (await card.isVisible({ timeout: 2000 }).catch(() => false)) {
        const cardBox = await card.boundingBox();
        if (cardBox) {
          await humanMove(cardBox.x + cardBox.width / 2, cardBox.y + cardBox.height / 2);
          await page.waitForTimeout(600);
        }
      }
    }

    await page.waitForTimeout(LONG_PAUSE);

    // ================================================================
    // FINAL: End
    // ================================================================
    markStep('end');
    console.log('[demo] Agent delete workflow demo complete!');

    // Write timestamps
    const fs = require('fs');
    const path = require('path');
    const scriptDir = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '..');
    const tsFile = path.join(scriptDir, '..', 'agent-delete-timestamps.json');
    fs.writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[demo] Timestamps written to ${tsFile}`);

    await page.waitForTimeout(10000);
  });
});
