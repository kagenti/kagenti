/**
 * Sandbox Agent Variants — Lightweight E2E Test
 *
 * Parameterized test that verifies each deployed agent variant can:
 * 1. Be selected in the Sandboxes panel
 * 2. Respond to a simple text prompt (fast-path: single-step plan)
 * 3. Execute a tool call via a simple shell command
 *
 * Prompts are crafted to produce single-step plans in the planner,
 * which skips the reflector and reporter LLM calls — keeping total
 * LLM round-trips to ~4 per test (planner + executor per turn).
 * Target: <2 minutes on Llama 4 Scout via LiteLLM.
 *
 * Variants tested: sandbox-legion, sandbox-hardened, sandbox-basic, sandbox-restricted
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-variants
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

const AGENT_TIMEOUT = 180_000;
const SCREENSHOT_DIR = 'test-results/sandbox-variants';

// Agent variants to test — each must be deployed on the cluster
const AGENT_VARIANTS = [
  'sandbox-legion',
  'sandbox-hardened',
  'sandbox-basic',
  'sandbox-restricted',
];

let screenshotIdx = 0;
async function snap(page: Page, label: string) {
  screenshotIdx++;
  const name = `${String(screenshotIdx).padStart(2, '0')}-${label}`;
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
}

/**
 * Navigate to sandbox with a specific agent via URL param.
 * Handles Keycloak login redirect if needed.
 */
async function navigateToSandboxWithAgent(page: Page, agentName: string) {
  await page.goto(`/sandbox?agent=${encodeURIComponent(agentName)}`);
  await page.waitForLoadState('networkidle');

  // Re-login if redirected to Keycloak
  if (page.url().includes('keycloak') || page.url().includes('auth/realms')) {
    await loginIfNeeded(page);
    await page.goto(`/sandbox?agent=${encodeURIComponent(agentName)}`);
    await page.waitForLoadState('networkidle');
  }

  // Confirm the agent badge renders
  const agentLabel = page
    .locator('[class*="pf-v5-c-label"]')
    .filter({ hasText: agentName });
  await expect(agentLabel.first()).toBeVisible({ timeout: 10000 });
}

/**
 * Send a message and wait for agent response.
 */
async function sendAndWait(
  page: Page,
  message: string,
  timeout = AGENT_TIMEOUT
): Promise<string> {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 10000 });
  await expect(chatInput).toBeEnabled({ timeout: 5000 });
  await chatInput.fill(message);

  const sendButton = page.getByRole('button', { name: /Send/i });
  await expect(sendButton).toBeEnabled({ timeout: 5000 });
  await sendButton.click();

  // Verify user message appears
  await expect(page.getByText(message).first()).toBeVisible({ timeout: 5000 });

  // Wait for agent to finish — the loop card must show "done" or "failed"
  // status, indicated by the summary bar showing a non-active status.
  // chatInput.toBeEnabled() fires too early while the loop is still executing.
  const loopCards = page.locator('[data-testid="agent-loop-card"]');
  await expect(loopCards.last()).toBeVisible({ timeout: 30000 });

  // Poll until no loop card shows "planning" or "executing" status
  // (both indicate the agent is still working)
  const activeStatuses = loopCards.last().locator('text=/planning|executing|reflecting/');
  for (let i = 0; i < 60; i++) {
    const count = await activeStatuses.count();
    if (count === 0) break;
    await page.waitForTimeout(2000);
  }
  await page.waitForTimeout(2000);

  // Get response content
  const chatArea = page.getByTestId('chat-messages');
  return (await chatArea.textContent()) || '';
}

// ===========================================================================
// PARAMETERIZED TESTS — one test per agent variant
// ===========================================================================

for (const agentName of AGENT_VARIANTS) {
  test.describe(`Agent Variant: ${agentName}`, () => {
    test(`multi-turn with tool call on ${agentName}`, async ({ page }) => {
      test.setTimeout(420_000);
      screenshotIdx = 0;

      const runId = Date.now().toString(36);
      const marker = `hello-${agentName}-${runId}`;

      // ---- Login & Select agent via URL ----
      await page.goto('/');
      await loginIfNeeded(page);
      await navigateToSandboxWithAgent(page, agentName);
      await snap(page, `${agentName}-selected`);

      // ---- Turn 1: Simple text response (single-step plan → fast path) ----
      await sendAndWait(page, `Say exactly: ${marker}`);
      await snap(page, `${agentName}-turn1`);

      // Verify we got a session
      const sessionId = new URL(page.url()).searchParams.get('session') || '';
      expect(sessionId).toBeTruthy();

      // ---- Turn 2: Tool call — minimal shell command (single-step plan) ----
      await sendAndWait(page, `Run: echo test-marker-${runId}`);
      await snap(page, `${agentName}-turn2-tool`);

      // ---- Assertions ----
      const fullContent = await page
        .getByTestId('chat-messages')
        .textContent() || '';

      // Verify our marker appears (user message echoed + agent response)
      expect(fullContent).toContain(marker);

      // Verify the tool call turn produced output containing the marker
      expect(fullContent).toContain(`test-marker-${runId}`);

      // Verify we got agent responses (not just user messages)
      expect(fullContent.length).toBeGreaterThan(marker.length * 2);

      await snap(page, `${agentName}-complete`);
    });
  });
}
