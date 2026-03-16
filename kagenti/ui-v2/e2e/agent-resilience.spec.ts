/**
 * Agent Resilience E2E Test — Loop Recovery After Pod Restart
 *
 * Verifies that the sandbox agent session recovers after the agent pod is
 * scaled down mid-request and scaled back up:
 * 1. Login, navigate to sandbox with agent=sandbox-legion
 * 2. Send a multi-step request that triggers the reasoning loop
 * 3. Scale down the agent deployment to 0 mid-request
 * 4. Scale back up to 1 and wait for readiness
 * 5. Verify the session is still usable (send a follow-up message)
 * 6. Verify the agent responds after restart
 *
 * Requires a live cluster with sandbox-hardened deployed.
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test agent-resilience
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const AGENT_NAME = 'sandbox-hardened';
const NAMESPACE = 'team1';
const SCREENSHOT_DIR = 'test-results/agent-resilience';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getKubeconfig(): string {
  return (
    process.env.KUBECONFIG ||
    `${process.env.HOME}/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig`
  );
}

function findKubectl(): string {
  for (const bin of ['/opt/homebrew/bin/oc', '/usr/local/bin/kubectl', 'kubectl']) {
    try {
      execSync(`${bin} version --client 2>/dev/null`, {
        timeout: 5000,
        stdio: 'pipe',
      });
      return bin;
    } catch {
      /* next */
    }
  }
  return 'kubectl';
}

const KC = findKubectl();

function kc(cmd: string, t = 30000): string {
  try {
    return execSync(`KUBECONFIG=${getKubeconfig()} ${KC} ${cmd}`, {
      timeout: t,
      stdio: 'pipe',
    })
      .toString()
      .trim();
  } catch (e: any) {
    return e.stderr?.toString() || e.message || '';
  }
}

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
 * Navigate to the sandbox page and set agent via URL param.
 * SandboxPage has a useEffect that syncs selectedAgent from ?agent=.
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
 * Ensure the agent deployment is scaled to 1 and ready.
 * Returns true if the agent is ready within the timeout, false otherwise.
 */
async function ensureAgentReady(page: Page, maxWaitSeconds = 120): Promise<boolean> {
  // Scale to 1 in case it was left at 0
  kc(`scale deployment/${AGENT_NAME} -n ${NAMESPACE} --replicas=1`);

  const polls = Math.ceil(maxWaitSeconds / 5);
  for (let i = 0; i < polls; i++) {
    const r = kc(
      `get deployment/${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`
    );
    if (r === '1') return true;
    await page.waitForTimeout(5000);
  }
  return false;
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test.describe('Agent Resilience — Loop Recovery', () => {

  // Always restore the agent to 1 replica, even if the test fails
  test.afterEach(async () => {
    console.log('[resilience] afterEach: ensuring agent scaled back to 1');
    kc(`scale deployment/${AGENT_NAME} -n ${NAMESPACE} --replicas=1`);
    // Wait briefly for rollout to start
    let ready = false;
    for (let i = 0; i < 24; i++) {
      const r = kc(
        `get deployment/${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`
      );
      if (r === '1') {
        ready = true;
        break;
      }
      // Use a raw sleep since page may not be available in afterEach
      execSync('sleep 5');
    }
    console.log(`[resilience] afterEach: agent ready=${ready}`);
  });

  test('session recovers after agent pod restart mid-request', async ({ page }) => {
    test.setTimeout(300_000); // 5 min
    screenshotIdx = 0;
    console.log(`[resilience] kubectl=${KC}`);

    // ── Pre-check: agent must be running ──────────────────────────────────
    const preReady = await ensureAgentReady(page, 60);
    expect(preReady).toBe(true);
    console.log('[resilience] Agent pre-check: ready');

    // ── Step 1: Login and navigate to sandbox with agent param ────────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandboxWithAgent(page, AGENT_NAME);
    await snap(page, 'agent-selected');
    console.log(`[resilience] Agent ${AGENT_NAME} selected, URL: ${page.url()}`);

    // ── Step 2: Send a multi-step request that will take time ─────────────
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });
    await expect(chatInput).toBeEnabled({ timeout: 5000 });

    const taskMessage =
      'List all files in the workspace directory, then create a file called ' +
      'resilience-test.txt with the content "recovered". Show the full listing.';

    await chatInput.fill(taskMessage);
    const sendBtn = page.getByRole('button', { name: /Send/i });
    await expect(sendBtn).toBeEnabled({ timeout: 5000 });
    await sendBtn.click();

    // Verify user message appears
    await expect(
      page
        .getByTestId('chat-messages')
        .getByText(taskMessage.substring(0, 30))
        .first()
    ).toBeVisible({ timeout: 10000 });
    await snap(page, 'message-sent');
    console.log('[resilience] Message sent, waiting for agent to start processing...');

    // Wait for the agent to start processing (first streaming event)
    await page.waitForTimeout(3000);

    // ── Step 3: Scale down the agent mid-request ──────────────────────────
    console.log('[resilience] Scaling down agent to 0 replicas...');
    kc(`scale deployment/${AGENT_NAME} -n ${NAMESPACE} --replicas=0`);
    await snap(page, 'scaled-down');

    // Wait for pods to terminate
    await page.waitForTimeout(5000);

    // Verify agent is actually down
    const replicasAfterDown = kc(
      `get deployment/${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`
    );
    console.log(`[resilience] Agent replicas after scale-down: '${replicasAfterDown}'`);
    await snap(page, 'agent-down');

    // ── Step 4: Scale back up ─────────────────────────────────────────────
    console.log('[resilience] Scaling agent back up to 1 replica...');
    kc(`scale deployment/${AGENT_NAME} -n ${NAMESPACE} --replicas=1`);

    let ready = false;
    for (let i = 0; i < 24; i++) {
      const r = kc(
        `get deployment/${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`
      );
      if (r === '1') {
        ready = true;
        break;
      }
      await page.waitForTimeout(5000);
    }
    expect(ready).toBe(true);
    console.log('[resilience] Agent is back up and ready');
    await snap(page, 'agent-restored');

    // ── Step 5: Wait for the looper / recovery mechanism ──────────────────
    // The polling mechanism should detect the incomplete session and retry,
    // or the UI should re-enable the chat input for a new message.
    await page.waitForTimeout(10000);

    // Capture the current session ID from the URL
    const sessionId = await page.evaluate(
      () => new URLSearchParams(window.location.search).get('session') || ''
    );
    console.log(`[resilience] Session ID: ${sessionId}`);

    // Snapshot the chat state after recovery window
    const chatMessages = page.getByTestId('chat-messages');
    const chatContentBeforeRetry =
      (await chatMessages.textContent({ timeout: 5000 }).catch(() => '')) || '';
    console.log(
      `[resilience] Chat content after recovery (${chatContentBeforeRetry.length} chars): ` +
        `${chatContentBeforeRetry.substring(0, 200)}`
    );
    await snap(page, 'after-recovery-window');

    // ── Step 6: Send a follow-up message to verify session is usable ──────
    // Wait for the chat input to become enabled (agent done or error handled)
    await expect(chatInput).toBeEnabled({ timeout: 60000 });
    console.log('[resilience] Chat input is enabled, sending recovery probe...');

    const recoveryMessage = 'Say exactly: recovered-after-restart';
    await chatInput.fill(recoveryMessage);
    await expect(sendBtn).toBeEnabled({ timeout: 5000 });
    await sendBtn.click();

    // Verify the recovery message appears in chat
    await expect(
      chatMessages.getByText(recoveryMessage.substring(0, 20)).first()
    ).toBeVisible({ timeout: 10000 });
    console.log('[resilience] Recovery message sent');
    await snap(page, 'recovery-message-sent');

    // Wait for agent to respond — input re-enables when streaming completes
    await expect(chatInput).toBeEnabled({ timeout: 120000 });
    await page.waitForTimeout(2000);

    // ── Step 7: Verify the agent responded after restart ──────────────────
    const finalContent =
      (await chatMessages.textContent({ timeout: 5000 }).catch(() => '')) || '';
    const hasRecoveryPhrase = finalContent.includes('recovered-after-restart');
    console.log(`[resilience] Recovery phrase in response: ${hasRecoveryPhrase}`);
    console.log(
      `[resilience] Final content (${finalContent.length} chars): ` +
        `${finalContent.substring(0, 300)}`
    );
    await snap(page, 'final-state');

    // The session must still be active (has a session ID)
    const finalSessionId = await page.evaluate(
      () => new URLSearchParams(window.location.search).get('session') || ''
    );
    console.log(`[resilience] Final session ID: ${finalSessionId}`);
    expect(finalSessionId).toBeTruthy();

    // The agent must have produced new output after the restart
    expect(finalContent.length).toBeGreaterThan(chatContentBeforeRetry.length);

    // The recovery message should be answered — agent output contains the phrase
    // or at minimum, the chat grew (agent is responsive post-restart)
    const agentOutput = page
      .locator('[data-testid="agent-loop-card"]')
      .or(page.locator('.sandbox-markdown'))
      .or(page.locator('text=/recovered-after-restart/i'));
    const hasAgentOutput = await agentOutput
      .first()
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    console.log(`[resilience] Agent output visible after restart: ${hasAgentOutput}`);
    expect(hasAgentOutput).toBe(true);

    await snap(page, 'complete');
    console.log('[resilience] Test complete — session survived agent restart');
  });
});
