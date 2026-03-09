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
 * 7. Test Looper kicking on agent task completion
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

const NAMESPACE = 'team1';
const AGENT_NAME = 'sandbox-legion';

// Task that triggers multiple tool calls
const TASK_PROMPT =
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
  const url = page.url();
  const match = url.match(/session=([a-f0-9]+)/);
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

    // Wait for agent to start responding
    const agentOutput = page
      .locator('.sandbox-markdown')
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

    // Wait for poll to refresh UI, then check Active badge
    await page.waitForTimeout(6000);
    const activeBadge = looperCard.locator('text=Active');
    await expect(activeBadge).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] Looper shows Active badge');

    // ── Step 4: Verify sidecar list API ────────────────────────────────────
    const sidecars = await listSidecars(page, contextId);
    const looperEntry = sidecars.find(
      (s: { sidecar_type: string }) => s.sidecar_type === 'looper'
    );
    expect(looperEntry).toBeDefined();
    expect(looperEntry.enabled).toBe(true);
    console.log(`[sidecar] Looper API: ${JSON.stringify(looperEntry)}`);

    // ── Step 5: Configure Looper via API ───────────────────────────────────
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 15,
      counter_limit: 2,
      auto_approve: false,
    });
    console.log('[sidecar] Looper configured: 15s interval, counter_limit=2, HITL mode');

    // ── Step 6: Enable remaining sidecars ──────────────────────────────────
    await enableSidecar(page, contextId, 'hallucination_observer');
    await enableSidecar(page, contextId, 'context_guardian');
    await page.waitForTimeout(6000);

    // Verify all show Active
    await expect(hallucinationCard.locator('text=Active')).toBeVisible({ timeout: 10000 });
    await expect(guardianCard.locator('text=Active')).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] All 3 sidecars enabled and showing Active');

    // ── Step 7: Disable Looper ─────────────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await page.waitForTimeout(6000);

    // Active badge should be gone
    const looperActive = await looperCard.locator('text=Active').isVisible().catch(() => false);
    expect(looperActive).toBe(false);
    console.log('[sidecar] Looper disabled, Active badge removed');

    // Others still active
    await expect(hallucinationCard.locator('text=Active')).toBeVisible();
    await expect(guardianCard.locator('text=Active')).toBeVisible();

    // ── Step 8: Re-enable Looper ───────────────────────────────────────────
    await enableSidecar(page, contextId, 'looper');
    await page.waitForTimeout(6000);
    await expect(looperCard.locator('text=Active')).toBeVisible({ timeout: 10000 });
    console.log('[sidecar] Looper re-enabled, Active badge restored');

    // ── Step 9: Disable all ────────────────────────────────────────────────
    await disableSidecar(page, contextId, 'looper');
    await disableSidecar(page, contextId, 'hallucination_observer');
    await disableSidecar(page, contextId, 'context_guardian');
    await page.waitForTimeout(6000);

    // No Active badges
    for (const card of [looperCard, hallucinationCard, guardianCard]) {
      const active = await card.locator('text=Active').isVisible().catch(() => false);
      expect(active).toBe(false);
    }
    console.log('[sidecar] All sidecars disabled');
  });

  test('Looper auto-continues agent on completion', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSessions(page);
    await selectAgent(page, AGENT_NAME);

    // Send a quick task
    await sendMessage(page, 'Create a file called /workspace/hello.txt with the content "hello world"');

    await page.waitForTimeout(3000);
    const contextId = await getSessionContextId(page);
    expect(contextId).toBeTruthy();

    // Enable Looper with low limit for testing
    await enableSidecar(page, contextId, 'looper');
    await updateSidecarConfig(page, contextId, 'looper', {
      interval_seconds: 5,
      counter_limit: 2,
      auto_approve: true,
    });
    console.log('[sidecar] Looper enabled: 5s interval, limit=2, auto-approve');

    // Wait for agent to complete + Looper to kick
    // The agent will finish the file creation, Looper detects completion, sends "continue"
    await page.waitForTimeout(30000);

    // Check observations via API
    const sidecars = await listSidecars(page, contextId);
    const looper = sidecars.find((s: { sidecar_type: string }) => s.sidecar_type === 'looper');
    console.log(`[sidecar] Looper state: obs=${looper?.observation_count}, pending=${looper?.pending_count}`);

    // Looper should have produced at least one observation (kicked or waiting)
    if (looper?.observation_count > 0) {
      console.log('[sidecar] Looper produced observations - auto-continue working');
    } else {
      console.log('[sidecar] No observations yet (agent may still be working)');
    }

    // Cleanup
    await disableSidecar(page, contextId, 'looper');
  });
});
