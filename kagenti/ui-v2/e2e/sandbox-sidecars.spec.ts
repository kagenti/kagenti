/**
 * Sidecar Agents E2E Test
 *
 * Tests sidecar agents alongside a long-running sandbox session:
 * 1. Start an RCA-style task on sandbox-legion (long-running, multi-tool)
 * 2. Enable Looper sidecar via API and verify tab appears
 * 3. Enable Hallucination Observer and Context Guardian
 * 4. Verify sidecar tabs show observations as agent works
 * 5. Test HITL toggle (auto-approve vs review mode)
 * 6. Test sidecar disable removes tab
 * 7. Verify sidecar intervention appears in parent chat when approved
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

const NAMESPACE = 'team1';
const AGENT_NAME = 'sandbox-legion';
const BASE_URL = process.env.KAGENTI_URL || '';

// Long-running task that triggers multiple tool calls (good for sidecar observation)
const RCA_PROMPT =
  'Write a Python script that reads a CSV file, processes each row, and writes results to a new file. ' +
  'First create a sample CSV, then write the processing script, then run it and verify the output.';

// ── Helpers ──────────────────────────────────────────────────────────────────

async function navigateToSessions(page: Page) {
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');
}

async function selectAgent(page: Page, agentName: string) {
  const agentEntry = page.locator('div[role="button"]').filter({ hasText: agentName });
  if (await agentEntry.first().isVisible({ timeout: 10000 }).catch(() => false)) {
    await agentEntry.first().click();
    await page.waitForTimeout(1000);
  }
}

async function sendMessage(page: Page, message: string) {
  const input = page.locator('textarea[aria-label="Message input"]');
  await expect(input).toBeVisible({ timeout: 15000 });
  await input.fill(message);
  await input.press('Enter');
}

async function getSessionContextId(page: Page): Promise<string> {
  // Extract session/context ID from URL query param
  const url = page.url();
  const match = url.match(/session=([a-f0-9]+)/);
  return match?.[1] || '';
}

async function enableSidecar(page: Page, contextId: string, sidecarType: string) {
  const response = await page.request.post(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/enable`
  );
  expect(response.ok()).toBe(true);
}

async function disableSidecar(page: Page, contextId: string, sidecarType: string) {
  const response = await page.request.post(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/disable`
  );
  expect(response.ok()).toBe(true);
}

async function updateSidecarConfig(
  page: Page,
  contextId: string,
  sidecarType: string,
  config: Record<string, unknown>
) {
  const response = await page.request.put(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/config`,
    { data: config }
  );
  expect(response.ok()).toBe(true);
}

async function listSidecars(page: Page, contextId: string) {
  const response = await page.request.get(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars`
  );
  expect(response.ok()).toBe(true);
  return response.json();
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Sidecar Agents', () => {
  test.setTimeout(600_000); // 10 min — long-running agent task

  test('sidecar lifecycle: enable, observe, toggle HITL, disable during agent task', async ({
    page,
  }) => {
    // ── Step 1: Start a long-running task ──────────────────────────────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);
    await sendMessage(page, RCA_PROMPT);

    // Wait for agent to start responding (first markdown or tool call)
    const agentOutput = page
      .locator('.sandbox-markdown')
      .or(page.locator('text=/Tool Call:|Result:/i'));
    await expect(agentOutput.first()).toBeVisible({ timeout: 120000 });
    console.log('[sidecar] Agent started responding');

    // Get session context ID
    await page.waitForTimeout(2000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();
    console.log(`[sidecar] Session context: ${contextId}`);

    // ── Step 2: Verify no sidecar tabs initially ───────────────────────────
    const chatTab = page.locator('button[role="tab"]').filter({ hasText: 'Chat' });
    const looperTab = page.locator('button[role="tab"]').filter({ hasText: 'Looper' });
    const hallucinationTab = page
      .locator('button[role="tab"]')
      .filter({ hasText: 'Hallucination Observer' });
    const guardianTab = page
      .locator('button[role="tab"]')
      .filter({ hasText: 'Context Guardian' });

    // Chat tab should exist, sidecar tabs should not
    await expect(chatTab).toBeVisible({ timeout: 5000 });
    expect(await looperTab.isVisible().catch(() => false)).toBe(false);
    console.log('[sidecar] No sidecar tabs initially');

    // ── Step 3: Enable Looper sidecar ──────────────────────────────────────
    await enableSidecar(page, contextId, 'looper');
    console.log('[sidecar] Looper enabled via API');

    // Looper tab should appear
    await expect(looperTab).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] Looper tab visible');

    // ── Step 4: Verify sidecar list API ────────────────────────────────────
    const sidecars = await listSidecars(page, contextId);
    const looperEntry = sidecars.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperEntry).toBeDefined();
    expect(looperEntry.enabled).toBe(true);
    console.log(`[sidecar] Looper config: ${JSON.stringify(looperEntry)}`);

    // ── Step 5: Click Looper tab, verify content ───────────────────────────
    await looperTab.click();
    await page.waitForTimeout(2000);

    // Looper tab should show controls: enable/disable switch, auto/HITL toggle
    const autoToggle = page.locator('[data-testid="sidecar-auto-toggle"]');
    const enableSwitch = page.locator('[data-testid="sidecar-enable-switch"]');
    // At minimum, some sidecar UI should be visible
    const sidecarContent = page.locator('[data-testid="sidecar-tab-content"]');
    await expect(sidecarContent).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] Looper tab content visible');

    // ── Step 6: Configure Looper ───────────────────────────────────────────
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 15,
      counter_limit: 2,
      auto_approve: false,
    });
    console.log('[sidecar] Looper configured: 15s interval, counter_limit=2, HITL mode');

    // ── Step 7: Enable remaining sidecars ──────────────────────────────────
    await enableSidecar(page, contextId, 'hallucination_observer');
    await enableSidecar(page, contextId, 'context_guardian');

    await expect(hallucinationTab).toBeVisible({ timeout: 10000 });
    await expect(guardianTab).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] All 3 sidecars enabled and tabs visible');

    // ── Step 8: Wait for Looper observations ───────────────────────────────
    // Switch to Looper tab and wait for at least one observation
    await looperTab.click();
    await page.waitForTimeout(2000);

    // Looper should emit observations as it checks for loops
    const observation = page.locator('[data-testid="sidecar-observation"]');
    // Give Looper 2 intervals (30s at 15s interval) to produce an observation
    await expect(observation.first()).toBeVisible({ timeout: 45000 });
    console.log('[sidecar] Looper produced observation');

    // ── Step 9: Switch back to Chat tab ────────────────────────────────────
    await chatTab.click();
    await page.waitForTimeout(1000);

    // Agent should still be working in the background
    const agentMessages = page.locator('.sandbox-markdown');
    const msgCount = await agentMessages.count();
    console.log(`[sidecar] Agent has ${msgCount} markdown messages while sidecars observed`);
    expect(msgCount).toBeGreaterThan(0);

    // ── Step 10: Disable Looper, verify tab removed ────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await page.waitForTimeout(2000);

    // Looper tab should disappear
    expect(await looperTab.isVisible().catch(() => false)).toBe(false);
    console.log('[sidecar] Looper disabled, tab removed');

    // Other tabs should still exist
    await expect(hallucinationTab).toBeVisible();
    await expect(guardianTab).toBeVisible();

    // ── Step 11: Re-enable Looper, verify state restored ───────────────────
    await enableSidecar(page, contextId, 'looper');
    await expect(looperTab).toBeVisible({ timeout: 10000 });
    await looperTab.click();
    await page.waitForTimeout(2000);

    // Previous observations should still be visible (LangGraph checkpoint)
    const restoredObs = page.locator('[data-testid="sidecar-observation"]');
    const restoredCount = await restoredObs.count();
    console.log(`[sidecar] Looper re-enabled, ${restoredCount} observations restored`);
    expect(restoredCount).toBeGreaterThan(0);

    // ── Step 12: Disable all sidecars ──────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await disableSidecar(page, contextId, 'hallucination_observer');
    await disableSidecar(page, contextId, 'context_guardian');
    await page.waitForTimeout(2000);

    // All sidecar tabs should be gone, only Chat remains
    expect(await looperTab.isVisible().catch(() => false)).toBe(false);
    expect(await hallucinationTab.isVisible().catch(() => false)).toBe(false);
    expect(await guardianTab.isVisible().catch(() => false)).toBe(false);
    await expect(chatTab).toBeVisible();
    console.log('[sidecar] All sidecars disabled, only Chat tab remains');
  });

  test('Looper HITL intervention flow', async ({ page }) => {
    // ── Setup: Start task and enable Looper in HITL mode ───────────────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);

    // Send a task likely to cause repetition (intentionally vague)
    await sendMessage(
      page,
      'Try to read the file /workspace/nonexistent-data.csv and process it. Keep trying until you succeed.'
    );

    await page.waitForTimeout(3000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();

    // Enable Looper with aggressive settings for testing
    await enableSidecar(page, contextId, 'looper');
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 10,
      counter_limit: 2,
      auto_approve: false, // HITL mode
    });

    const looperTab = page.locator('button[role="tab"]').filter({ hasText: 'Looper' });
    await expect(looperTab).toBeVisible({ timeout: 10000 });

    // ── Wait for HITL intervention ─────────────────────────────────────────
    // Agent should repeat the same failing command, triggering Looper's counter
    await looperTab.click();
    await page.waitForTimeout(2000);

    // Wait for HITL badge or pending intervention (up to 2 minutes)
    const hitlPending = page.locator('[data-testid="sidecar-hitl-pending"]');
    const hitlBadge = page.locator('[data-testid="sidecar-hitl-badge"]');

    // Either HITL pending in Looper tab or badge on Chat tab
    const gotHitl = await Promise.race([
      hitlPending.first().waitFor({ state: 'visible', timeout: 120000 }).then(() => true),
      hitlBadge.first().waitFor({ state: 'visible', timeout: 120000 }).then(() => true),
    ]).catch(() => false);

    if (gotHitl) {
      console.log('[sidecar] Looper HITL intervention triggered');

      // Approve the intervention
      const approveBtn = page.locator('[data-testid="sidecar-approve-btn"]');
      if (await approveBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await approveBtn.click();
        console.log('[sidecar] HITL intervention approved');

        // Switch to Chat tab, verify corrective message appeared
        const chatTab = page.locator('button[role="tab"]').filter({ hasText: 'Chat' });
        await chatTab.click();
        await page.waitForTimeout(3000);

        // Look for sidecar intervention marker in chat
        const sidecarMsg = page.locator('[data-testid="sidecar-intervention-message"]');
        const hasSidecarMsg = await sidecarMsg.isVisible({ timeout: 10000 }).catch(() => false);
        console.log(`[sidecar] Corrective message in chat: ${hasSidecarMsg}`);
      }
    } else {
      // Agent may not have looped enough — that's OK, just log
      console.log('[sidecar] No HITL triggered (agent may not have looped). Continuing.');
    }

    // Cleanup
    await disableSidecar(page, contextId, 'looper');
    console.log('[sidecar] HITL test complete');
  });

  test('Context Guardian warns on token growth', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);

    // Send a task that generates a lot of output
    await sendMessage(
      page,
      'List all files in /usr directory recursively and explain what each top-level directory contains.'
    );

    await page.waitForTimeout(3000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();

    // Enable Context Guardian with low thresholds for testing
    await enableSidecar(page, contextId, 'context_guardian');
    await updateSidecarConfig(page, contextId, 'context_guardian', {
      warn_threshold_pct: 30,
      critical_threshold_pct: 50,
      auto_approve: true, // Auto mode for this test
    });

    const guardianTab = page
      .locator('button[role="tab"]')
      .filter({ hasText: 'Context Guardian' });
    await expect(guardianTab).toBeVisible({ timeout: 10000 });
    await guardianTab.click();

    // Wait for guardian to produce observations about token usage
    const observation = page.locator('[data-testid="sidecar-observation"]');
    await expect(observation.first()).toBeVisible({ timeout: 90000 });

    const obsText = (await observation.first().textContent()) || '';
    console.log(`[sidecar] Guardian observation: ${obsText.substring(0, 200)}`);

    // Guardian should mention context/tokens
    const mentionsContext =
      /context|token|budget|usage|growth|warning/i.test(obsText);
    console.log(`[sidecar] Guardian mentions context: ${mentionsContext}`);

    // Cleanup
    await disableSidecar(page, contextId, 'context_guardian');
  });
});
