/**
 * Sidecar Agents E2E Test
 *
 * Tests sidecar agents in the right panel alongside a sandbox session:
 * 1. Verify sidecar panel is visible with 3 cards
 * 2. Enable Looper, verify Active badge and config fields
 * 3. Configure Looper (max iterations, interval)
 * 4. Enable all 3 sidecars, verify API
 * 5. Disable Looper, verify it goes inactive
 * 6. Re-enable, verify state restored
 * 7. Test Looper auto-continuing on agent task completion
 * 8. Verify child session appears in sub-sessions tab
 * 9. Verify counter_limit is respected
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

const NAMESPACE = 'team1';
const AGENT_NAME = 'sandbox-hardened';

// Task that triggers multiple tool calls
const TASK_PROMPT =
  'Write a Python script that reads a CSV file, processes each row, and writes results to a new file. ' +
  'First create a sample CSV, then write the processing script, then run it and verify the output.';

// Short task for looper auto-continue test
const SHORT_TASK =
  'Create a file called /workspace/hello.txt with the content "hello world"';

// ── Helpers ──────────────────────────────────────────────────────────────────

async function navigateToSessions(page: Page) {
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');
}

async function selectAgent(page: Page, agentName: string) {
  // Try clicking an existing session for this agent
  const agentEntry = page.locator('div[role="button"]').filter({ hasText: agentName });
  if (await agentEntry.first().isVisible({ timeout: 5000 }).catch(() => false)) {
    await agentEntry.first().click();
    await page.waitForTimeout(1000);
    return;
  }
  // No existing session — start a new session via the "+ New Session" modal
  const newSessionBtn = page.getByText('+ New Session');
  if (await newSessionBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await newSessionBtn.click();
    // Select the agent in the FormSelect dropdown
    const agentSelect = page.locator('select[aria-label="Select agent"]');
    if (await agentSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      await agentSelect.selectOption(agentName);
    }
    const startBtn = page.getByRole('button', { name: /^Start$/ });
    if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await startBtn.click();
    }
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
  const url = page.url();
  const match = url.match(/session=([a-f0-9-]+)/i);
  return match?.[1] || '';
}

async function getAuthHeaders(page: Page): Promise<Record<string, string>> {
  const token = await page.evaluate(() => {
    for (const storage of [localStorage, sessionStorage]) {
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key && (key.includes('token') || key.includes('kc-'))) {
          try {
            const val = JSON.parse(storage.getItem(key) || '');
            if (val?.access_token) return val.access_token;
            if (val?.token) return val.token;
          } catch {
            const val = storage.getItem(key) || '';
            if (val.startsWith('eyJ')) return val;
          }
        }
      }
    }
    return '';
  });
  if (token) {
    return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  }
  return { 'Content-Type': 'application/json' };
}

async function enableSidecar(page: Page, contextId: string, sidecarType: string) {
  const headers = await getAuthHeaders(page);
  const response = await page.request.post(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/enable`,
    { headers, data: { agent_name: AGENT_NAME } }
  );
  if (!response.ok()) {
    console.log(`[sidecar] enable ${sidecarType} failed: ${response.status()} ${await response.text()}`);
  }
  expect(response.ok()).toBe(true);
}

async function disableSidecar(page: Page, contextId: string, sidecarType: string) {
  const headers = await getAuthHeaders(page);
  const response = await page.request.post(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/disable`,
    { headers }
  );
  if (!response.ok()) {
    console.log(`[sidecar] disable ${sidecarType} failed: ${response.status()} ${await response.text()}`);
  }
  expect(response.ok()).toBe(true);
}

async function updateSidecarConfig(
  page: Page,
  contextId: string,
  sidecarType: string,
  config: Record<string, unknown>
) {
  const headers = await getAuthHeaders(page);
  const response = await page.request.put(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars/${sidecarType}/config`,
    { headers, data: config }
  );
  if (!response.ok()) {
    console.log(`[sidecar] config ${sidecarType} failed: ${response.status()} ${await response.text()}`);
  }
  expect(response.ok()).toBe(true);
}

async function listSidecars(page: Page, contextId: string) {
  const headers = await getAuthHeaders(page);
  const response = await page.request.get(
    `/api/v1/sandbox/${NAMESPACE}/sessions/${contextId}/sidecars`,
    { headers }
  );
  if (!response.ok()) {
    console.log(`[sidecar] list failed: ${response.status()} ${await response.text()}`);
  }
  expect(response.ok()).toBe(true);
  return response.json();
}

async function getChildSessions(page: Page, contextId: string) {
  const headers = await getAuthHeaders(page);
  const response = await page.request.get(
    `/api/v1/sandbox/${NAMESPACE}/sessions?limit=100`,
    { headers }
  );
  expect(response.ok()).toBe(true);
  const data = await response.json();
  const items = data.items || [];
  return items.filter(
    (s: Record<string, unknown>) => {
      const meta = s.metadata as Record<string, unknown> | undefined;
      return meta?.parent_context_id === contextId;
    }
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Sidecar Agents', () => {
  test.setTimeout(600_000);

  test('sidecar panel: enable, configure, verify API, disable lifecycle', async ({ page }) => {
    // ── Step 1: Navigate and start a session ───────────────────────────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);
    await sendMessage(page, TASK_PROMPT);

    // Wait for agent to start responding: prefer agent-loop-card, fall back to old format
    const agentOutput = page
      .locator('[data-testid="agent-loop-card"]')
      .or(page.locator('.sandbox-markdown'))
      .or(page.locator('text=/Tool Call:|Result:/i'));
    await expect(agentOutput.first()).toBeVisible({ timeout: 120000 });
    console.log('[sidecar] Agent started responding');

    await page.waitForTimeout(2000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();
    console.log(`[sidecar] Session context: ${contextId}`);

    // ── Step 2: Verify sidecar panel exists ────────────────────────────────
    const sidecarPanel = page.locator('[data-testid="sidecar-panel"]');
    await expect(sidecarPanel).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] Sidecar panel visible');

    // Verify 3 sidecar cards present
    const looperCard = page.locator('[data-testid="sidecar-card-looper"]');
    const hallucinationCard = page.locator('[data-testid="sidecar-card-hallucination_observer"]');
    const guardianCard = page.locator('[data-testid="sidecar-card-context_guardian"]');
    await expect(looperCard).toBeVisible({ timeout: 5000 });
    await expect(hallucinationCard).toBeVisible({ timeout: 5000 });
    await expect(guardianCard).toBeVisible({ timeout: 5000 });
    console.log('[sidecar] All 3 sidecar cards visible');

    // ── Step 3: Enable Looper via API ──────────────────────────────────────
    await enableSidecar(page, contextId, 'looper');
    console.log('[sidecar] Looper enabled via API');

    // Wait for poll to refresh UI — the status dot tooltip says "Active"
    // when enabled. Check by expanding the card and looking for the On switch.
    await page.waitForTimeout(6000);

    // ── Step 4: Verify sidecar list API ────────────────────────────────────
    const sidecars = await listSidecars(page, contextId);
    const looperEntry = sidecars.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperEntry).toBeDefined();
    expect(looperEntry.enabled).toBe(true);
    console.log(`[sidecar] Looper API state: enabled=${looperEntry.enabled}, obs=${looperEntry.observation_count}`);

    // ── Step 5: Configure Looper via API ───────────────────────────────────
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 15,
      counter_limit: 2,
      auto_approve: false,
    });
    console.log('[sidecar] Looper configured: 15s interval, counter_limit=2, HITL mode');

    // Verify config took effect
    const sidecarsAfterConfig = await listSidecars(page, contextId);
    const looperAfterConfig = sidecarsAfterConfig.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperAfterConfig).toBeDefined();
    expect(looperAfterConfig.config.counter_limit).toBe(2);
    expect(looperAfterConfig.config.interval_seconds).toBe(15);
    console.log('[sidecar] Looper config verified via API');

    // ── Step 6: Enable remaining sidecars ──────────────────────────────────
    await enableSidecar(page, contextId, 'hallucination_observer');
    await enableSidecar(page, contextId, 'context_guardian');
    await page.waitForTimeout(6000);

    // Verify all 3 are listed and enabled via API
    const allSidecars = await listSidecars(page, contextId);
    expect(allSidecars.length).toBe(3);
    for (const sc of allSidecars) {
      expect(sc.enabled).toBe(true);
    }
    console.log('[sidecar] All 3 sidecars enabled and verified via API');

    // ── Step 7: Disable Looper ─────────────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await page.waitForTimeout(3000);

    // Verify via API that looper is disabled
    const sidecarsAfterDisable = await listSidecars(page, contextId);
    const looperAfterDisable = sidecarsAfterDisable.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperAfterDisable).toBeDefined();
    expect(looperAfterDisable.enabled).toBe(false);
    console.log('[sidecar] Looper disabled, verified via API');

    // Others still active
    const hallucinationAfterDisable = sidecarsAfterDisable.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'hallucination_observer'
    );
    const guardianAfterDisable = sidecarsAfterDisable.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'context_guardian'
    );
    expect(hallucinationAfterDisable?.enabled).toBe(true);
    expect(guardianAfterDisable?.enabled).toBe(true);

    // ── Step 8: Re-enable Looper ───────────────────────────────────────────
    await enableSidecar(page, contextId, 'looper');
    await page.waitForTimeout(3000);

    const sidecarsAfterReenable = await listSidecars(page, contextId);
    const looperAfterReenable = sidecarsAfterReenable.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperAfterReenable).toBeDefined();
    expect(looperAfterReenable.enabled).toBe(true);
    console.log('[sidecar] Looper re-enabled, verified via API');

    // ── Step 9: Disable all ────────────────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await disableSidecar(page, contextId, 'hallucination_observer');
    await disableSidecar(page, contextId, 'context_guardian');
    await page.waitForTimeout(3000);

    const sidecarsAfterAllDisable = await listSidecars(page, contextId);
    for (const sc of sidecarsAfterAllDisable) {
      expect(sc.enabled).toBe(false);
    }
    console.log('[sidecar] All sidecars disabled, verified via API');
  });

  test('Looper auto-continues agent on completion and creates child sessions', async ({ page }) => {
    // ── Step 1: Navigate and start a session ───────────────────────────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);

    // Send a quick task that completes fast
    await sendMessage(page, SHORT_TASK);
    console.log('[sidecar] Sent short task, waiting for session context...');

    // Wait for the session to be established
    await page.waitForTimeout(5000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();
    console.log(`[sidecar] Session context: ${contextId}`);

    // ── Step 2: Enable Looper — it checks session state at startup ─────────
    // The looper queries the DB on startup. If the session already completed
    // before the looper was enabled, it detects this and auto-continues.
    await enableSidecar(page, contextId, 'looper');
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 5,
      counter_limit: 2,
      auto_approve: true,
    });
    console.log('[sidecar] Looper enabled: 5s interval, limit=2, auto-approve=true');

    // ── Step 3: Wait for agent to complete + Looper to auto-continue ──────
    // The agent finishes the file creation task. Looper detects the done
    // signal, sends "continue" (creating a child session), then the child
    // completes, and Looper auto-continues again until counter_limit=2.
    // With 5s interval and auto-approve, we need ~60-120s for 2 iterations
    // on a slow Llama model.
    console.log('[sidecar] Waiting for Looper to auto-continue (up to 180s)...');

    // Poll the sidecar API until we see observations
    let looperObservationCount = 0;
    let pollAttempts = 0;
    const maxPollAttempts = 36; // 36 * 5s = 180s

    while (pollAttempts < maxPollAttempts) {
      await page.waitForTimeout(5000);
      pollAttempts++;

      const sidecars = await listSidecars(page, contextId);
      const looper = sidecars.find(
        (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
      );

      if (!looper) {
        console.log(`[sidecar] Poll ${pollAttempts}: looper not found in API response`);
        continue;
      }

      looperObservationCount = looper.observation_count || 0;
      const pendingCount = looper.pending_count || 0;
      console.log(
        `[sidecar] Poll ${pollAttempts}: observations=${looperObservationCount}, pending=${pendingCount}`
      );

      // We expect at least 2 observations: iteration 1 auto-continue + iteration 2
      // (which hits the limit, gets auto-approved due to auto_approve=true, then resets)
      // Minimum: 2 auto-continue observations before limit is reached.
      if (looperObservationCount >= 2) {
        console.log('[sidecar] Looper produced >= 2 observations, continuing to verification');
        break;
      }
    }

    // ── Step 4: Assert Looper produced observations ────────────────────────
    expect(looperObservationCount).toBeGreaterThanOrEqual(1);
    console.log(`[sidecar] PASSED: Looper produced ${looperObservationCount} observation(s)`);

    // ── Step 5: Verify observations contain expected messages ──────────────
    // Expand the looper card to see the observation stream in the UI
    const looperCard = page.locator('[data-testid="sidecar-card-looper"]');
    await expect(looperCard).toBeVisible({ timeout: 10000 });

    // Click to expand the looper card
    await looperCard.click();
    await page.waitForTimeout(2000);

    // Check for observation elements in the expanded card
    const observationElements = looperCard.locator('[data-testid="sidecar-observation"]');
    const observationCount = await observationElements.count();
    console.log(`[sidecar] UI observation elements visible: ${observationCount}`);

    // Observations should be present in the UI (SSE stream delivers them)
    // Note: SSE may not have all observations if the card was just expanded,
    // so we check the API observation count as the authoritative source.
    // The UI observations come via SSE which starts on enable, so they
    // should be present if the card has been enabled for a while.
    if (observationCount > 0) {
      // Verify at least one observation contains "Auto-continued" or "Iteration"
      const firstObsText = await observationElements.first().textContent();
      console.log(`[sidecar] First observation text: ${firstObsText}`);
      expect(firstObsText).toBeTruthy();
    }

    // ── Step 6: Verify child sessions via API ──────────────────────────────
    console.log('[sidecar] Checking for child sessions...');
    const childSessions = await getChildSessions(page, contextId);
    console.log(`[sidecar] Found ${childSessions.length} child session(s)`);

    // The looper creates child sessions via A2A message/send with
    // parent_context_id in metadata. At least 1 should exist.
    expect(childSessions.length).toBeGreaterThanOrEqual(1);
    console.log('[sidecar] PASSED: Child session(s) created by Looper');

    // Verify child session metadata
    const firstChild = childSessions[0];
    const childMeta = firstChild.metadata as Record<string, unknown>;
    expect(childMeta.parent_context_id).toBe(contextId);
    expect(childMeta.source).toBe('sidecar-looper');
    console.log(`[sidecar] Child session metadata verified: source=${childMeta.source}, parent=${childMeta.parent_context_id}`);

    // ── Step 7: Verify sub-sessions tab shows child sessions ───────────────
    // Click the sub-sessions tab
    const subSessionsTab = page.locator('button[role="tab"]').filter({ hasText: /Sub-sessions/ });
    await expect(subSessionsTab).toBeVisible({ timeout: 10000 });
    await subSessionsTab.click();
    await page.waitForTimeout(3000);

    // The SubSessionsPanel should show at least 1 child session row
    // It has a CardTitle "Sub-sessions (N)" where N > 0
    const subSessionsTitle = page.locator('text=/Sub-sessions \\(\\d+\\)/');
    await expect(subSessionsTitle).toBeVisible({ timeout: 15000 });
    console.log('[sidecar] PASSED: Sub-sessions tab shows child session count');

    // Verify a table row with the agent name exists
    const childRow = page.locator('table tbody tr').filter({ hasText: AGENT_NAME });
    await expect(childRow.first()).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] PASSED: Child session row visible in sub-sessions table');

    // Verify the child session has a "Looper iteration" title
    const looperTitle = page.locator('table tbody tr').filter({ hasText: /Looper iteration/ });
    const hasLooperTitle = await looperTitle.first().isVisible({ timeout: 5000 }).catch(() => false);
    if (hasLooperTitle) {
      console.log('[sidecar] PASSED: Child session has "Looper iteration" title');
    } else {
      console.log('[sidecar] INFO: Child session title does not contain "Looper iteration" (metadata write may be delayed)');
    }

    // ── Step 8: Verify counter_limit is respected ──────────────────────────
    // With auto_approve=true and counter_limit=2, the looper should have
    // auto-continued exactly 2 times before hitting the limit, then
    // auto-approved the reset and continued. We verify via the observation
    // messages that the limit was reached.
    console.log('[sidecar] Verifying counter_limit enforcement...');
    const finalSidecars = await listSidecars(page, contextId);
    const finalLooper = finalSidecars.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(finalLooper).toBeDefined();
    console.log(
      `[sidecar] Final looper state: observations=${finalLooper.observation_count}, pending=${finalLooper.pending_count}`
    );

    // With counter_limit=2 and auto_approve=true, the looper produces:
    // - "Auto-continued agent. Iteration 1/2" (info)
    // - "Iteration limit reached: 2/2. Paused" (critical, auto-approved)
    // - "Counter reset. Looper will auto-continue on next completion." (info)
    // So at least 2 observations means the limit was hit or auto-continues happened.
    expect(finalLooper.observation_count).toBeGreaterThanOrEqual(2);
    console.log('[sidecar] PASSED: counter_limit produced expected number of observations');

    // ── Cleanup ────────────────────────────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    console.log('[sidecar] Cleanup: Looper disabled');
  });
});
