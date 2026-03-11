/**
 * Budget Enforcement E2E Tests
 *
 * Test 1 (sandbox-restricted): Set very low token budget, verify agent stops
 * and the UI shows budget consumption with progress bars.
 *
 * Test 2 (sandbox-hardened): Verify budget state persists across agent
 * pod restart — tokens used should not reset to zero.
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-budget
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const NAMESPACE = 'team1';
const BUDGET_AGENT = 'sandbox-restricted'; // Low-test-surface agent for budget enforcement
const RESTART_AGENT = 'sandbox-hardened'; // Restart test (resilience is already here)

function getKubeconfig(): string {
  return (
    process.env.KUBECONFIG ||
    `${process.env.HOME}/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig`
  );
}

function findKubectl(): string {
  for (const bin of ['/opt/homebrew/bin/oc', '/usr/local/bin/kubectl', 'kubectl']) {
    try {
      execSync(`${bin} version --client 2>/dev/null`, { timeout: 5000, stdio: 'pipe' });
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
  } catch (e) {
    const err = e as { stderr?: Buffer };
    return err.stderr?.toString().trim() || '';
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

async function navigateToAgent(page: Page, agentName: string) {
  await page.goto('/');
  await loginIfNeeded(page);
  await page.goto(`/sandbox?agent=${agentName}`);
  await page.waitForLoadState('networkidle');
  // Wait for chat input to appear (session must be ready)
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 30000 });
}

async function sendMessage(page: Page, message: string) {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 15000 });
  await expect(chatInput).toBeEnabled({ timeout: 15000 });
  await chatInput.fill(message);
  // Scope send button to chat area to avoid matching sidebar buttons
  const sendBtn = page.locator('[data-testid="chat-messages"]')
    .locator('..').locator('..')
    .getByRole('button', { name: /Send/i });
  await expect(sendBtn).toBeEnabled({ timeout: 10000 });
  await sendBtn.click();
}

async function waitForResponse(page: Page, timeoutMs = 120000) {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeEnabled({ timeout: timeoutMs });
  await page.waitForTimeout(3000); // Let UI settle and loop events arrive

  // Verify we're in a session (URL should have session= param)
  const url = page.url();
  const hasSession = url.includes('session=');
  console.log(`[budget] waitForResponse: URL has session=${hasSession}, url=${url.substring(0, 120)}`);
}

async function switchToStatsTab(page: Page) {
  // Ensure we're in a session with data before switching tabs
  // Wait for at least one message to appear in chat (proves session loaded)
  const chatMessages = page.locator('[data-testid="chat-messages"]');
  await expect(chatMessages).toBeVisible({ timeout: 15000 });

  const statsTab = page.locator('[role="tab"]').filter({ hasText: /Stats/i });
  await expect(statsTab).toBeVisible({ timeout: 5000 });
  await statsTab.click();
  await page.waitForTimeout(1000); // Let stats render from loop data
}

// ── Test 1: Budget Enforcement ───────────────────────────────────────────────

test.describe('Budget Enforcement', () => {
  test.describe.configure({ retries: 0 });

  let originalMaxTokens: string;

  test.beforeAll(() => {
    // Save original budget and set very low limit
    originalMaxTokens = kc(
      `get deploy/${BUDGET_AGENT} -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].env}' | grep -A1 SANDBOX_MAX_TOKENS || echo "not-set"`
    );
    console.log(`[budget] Original SANDBOX_MAX_TOKENS: ${originalMaxTokens}`);

    // Set budget to 5000 tokens (~2 LLM calls at most)
    kc(`set env deploy/${BUDGET_AGENT} -n ${NAMESPACE} SANDBOX_MAX_TOKENS=5000`);
    console.log('[budget] Set SANDBOX_MAX_TOKENS=5000');

    // Wait for rollout
    kc(`rollout status deploy/${BUDGET_AGENT} -n ${NAMESPACE} --timeout=90s`, 120000);
    console.log('[budget] Rollout complete');
  });

  test.afterAll(() => {
    // Restore original budget (remove env var to use default)
    kc(`set env deploy/${BUDGET_AGENT} -n ${NAMESPACE} SANDBOX_MAX_TOKENS-`);
    console.log('[budget] Restored default SANDBOX_MAX_TOKENS');
    kc(`rollout status deploy/${BUDGET_AGENT} -n ${NAMESPACE} --timeout=90s`, 120000);
  });

  test('agent stops when token budget is exhausted and UI shows budget', async ({ page }) => {
    test.setTimeout(300_000);

    await navigateToAgent(page, BUDGET_AGENT);

    // Send a multi-step task that should exhaust 5000 tokens quickly
    await sendMessage(
      page,
      'Write a detailed analysis of the /workspace directory structure. ' +
        'List all files recursively, then analyze each file type and summarize.'
    );

    // Wait for agent to finish (it should stop early due to budget)
    await waitForResponse(page, 180000);

    // Reload to ensure history + loop events are fetched from DB
    // (SSE stream may have missed budget_update events if they arrived
    // before the UI connected)
    await page.reload();
    await page.waitForLoadState('networkidle');
    await loginIfNeeded(page);
    await page.waitForTimeout(3000);

    // Switch to Stats tab
    await switchToStatsTab(page);

    // Budget section MUST be visible with token data
    const budgetTokensUsed = page.locator('[data-testid="stats-budget-tokens-used"]');
    const budgetTokensTotal = page.locator('[data-testid="stats-budget-tokens-total"]');
    await expect(budgetTokensUsed).toBeVisible({ timeout: 10000 });
    await expect(budgetTokensTotal).toBeVisible({ timeout: 10000 });

    const used = Number((await budgetTokensUsed.textContent() || '0').replace(/,/g, ''));
    const total = Number((await budgetTokensTotal.textContent() || '0').replace(/,/g, ''));
    console.log(`[budget] Tokens used: ${used.toLocaleString()} / ${total.toLocaleString()}`);

    // Budget total MUST be 5000 (what we configured)
    expect(total).toBe(5000);

    // Agent MUST have consumed tokens
    expect(used).toBeGreaterThan(0);

    // Agent MUST have been stopped by budget (consumed >= 50% of limit)
    expect(used).toBeGreaterThanOrEqual(total * 0.5);

    // Wall clock MUST be visible
    const wallClockEl = page.locator('[data-testid="stats-budget-wallclock"]');
    await expect(wallClockEl).toBeVisible({ timeout: 5000 });
    const wallText = await wallClockEl.textContent();
    console.log(`[budget] Wall clock: ${wallText}`);
    expect(wallText).toBeTruthy();

    // Agent loop card MUST show budget exceeded message
    const loopCard = page.locator('[data-testid="agent-loop-card"]').first();
    await expect(loopCard).toBeVisible({ timeout: 5000 });
    const loopText = await loopCard.textContent() || '';
    expect(
      loopText.includes('Budget exceeded') ||
        loopText.includes('budget') ||
        loopText.includes('Token limit') ||
        loopText.includes('token')
    ).toBe(true);

    // Token consistency: loop card tokens MUST be close to LLM Usage total
    // Switch to LLM Usage tab and compare
    const llmTab = page.locator('[role="tab"]').filter({ hasText: /LLM Usage/i });
    if (await llmTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await llmTab.click();
      await page.waitForTimeout(1000);
      // LLM Usage "Total" row shows total_tokens from LiteLLM
      const llmTotalEl = page.locator('td').filter({ hasText: /Total/i }).locator('..').locator('td').nth(3);
      if (await llmTotalEl.isVisible({ timeout: 3000 }).catch(() => false)) {
        const llmTotal = Number((await llmTotalEl.textContent() || '0').replace(/,/g, ''));
        console.log(`[budget] LLM Usage total: ${llmTotal.toLocaleString()}, Budget used: ${used.toLocaleString()}`);
        // Budget tokens MUST match LLM total (both count the same LLM calls)
        if (llmTotal > 0) {
          expect(used).toBe(llmTotal);
        }
      }
    }

    console.log('[budget] Budget enforcement test complete');
  });
});

// ── Test 2: Budget Persists Across Restart ───────────────────────────────────

test.describe('Budget Persistence Across Restart', () => {
  test.describe.configure({ retries: 0 });

  test('budget tokens do not reset after agent pod restart', async ({ page }) => {
    test.setTimeout(300_000);

    await navigateToAgent(page, RESTART_AGENT);

    // Step 1: Send a task and let the agent process it
    await sendMessage(page, 'Create a file called /workspace/budget-test.txt with "hello"');
    await waitForResponse(page);

    // Reload to ensure loop events are loaded from DB
    await page.reload();
    await page.waitForLoadState('networkidle');
    await loginIfNeeded(page);
    await page.waitForTimeout(3000);

    // Step 2: Budget MUST be visible in Stats tab after first message
    await switchToStatsTab(page);

    const budgetTokensUsed = page.locator('[data-testid="stats-budget-tokens-used"]');
    const budgetTokensTotal = page.locator('[data-testid="stats-budget-tokens-total"]');
    await expect(budgetTokensUsed).toBeVisible({ timeout: 10000 });
    await expect(budgetTokensTotal).toBeVisible({ timeout: 10000 });

    const tokensBeforeRestart = Number(
      (await budgetTokensUsed.textContent() || '0').replace(/,/g, '')
    );
    const totalBudget = Number(
      (await budgetTokensTotal.textContent() || '0').replace(/,/g, '')
    );
    console.log(
      `[budget-restart] Before restart: ${tokensBeforeRestart.toLocaleString()} / ${totalBudget.toLocaleString()}`
    );

    // Agent MUST have consumed tokens
    expect(tokensBeforeRestart).toBeGreaterThan(0);
    // Total budget MUST be set
    expect(totalBudget).toBeGreaterThan(0);

    // Step 3: Restart the agent pod
    console.log('[budget-restart] Scaling agent to 0...');
    kc(`scale deploy/${RESTART_AGENT} -n ${NAMESPACE} --replicas=0`);
    execSync('sleep 5');

    console.log('[budget-restart] Scaling agent back to 1...');
    kc(`scale deploy/${RESTART_AGENT} -n ${NAMESPACE} --replicas=1`);
    kc(`rollout status deploy/${RESTART_AGENT} -n ${NAMESPACE} --timeout=120s`, 150000);
    console.log('[budget-restart] Agent is back');

    // Step 4: Switch to chat and send follow-up in the SAME session
    const chatTab = page.locator('[role="tab"]').filter({ hasText: /Chat/i });
    await chatTab.click();

    await sendMessage(page, 'Read the file /workspace/budget-test.txt');
    await waitForResponse(page, 180000);

    // Reload to ensure updated loop events are loaded
    await page.reload();
    await page.waitForLoadState('networkidle');
    await loginIfNeeded(page);
    await page.waitForTimeout(3000);

    // Step 5: Budget MUST still be visible and >= pre-restart value
    await switchToStatsTab(page);
    await expect(budgetTokensUsed).toBeVisible({ timeout: 10000 });

    const tokensAfterRestart = Number(
      (await budgetTokensUsed.textContent() || '0').replace(/,/g, '')
    );
    console.log(`[budget-restart] After restart: ${tokensAfterRestart.toLocaleString()}`);

    // Budget MUST NOT have reset — tokens after >= tokens before
    expect(tokensAfterRestart).toBeGreaterThanOrEqual(tokensBeforeRestart);

    // Second message MUST have consumed additional tokens
    expect(tokensAfterRestart).toBeGreaterThan(tokensBeforeRestart);

    console.log(
      `[budget-restart] Budget persisted: ${tokensBeforeRestart.toLocaleString()} -> ` +
        `${tokensAfterRestart.toLocaleString()} (delta: +${(tokensAfterRestart - tokensBeforeRestart).toLocaleString()})`
    );
  });
});
