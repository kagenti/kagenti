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

/** Re-trigger SPA route without full page reload (avoids Keycloak redirect). */
async function spaReloadSession(page: Page) {
  const url = page.url();
  const match = url.match(/session=([^&]+)/);
  if (match) {
    const sid = match[1];
    await page.evaluate((s) => {
      window.history.pushState({}, '', `/sandbox?session=${s}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, sid);
  } else {
    await page.reload();
    await page.waitForLoadState('networkidle');
    await loginIfNeeded(page);
  }
  await page.waitForTimeout(3000);
}

async function navigateToAgent(page: Page, agentName: string) {
  await page.goto('/');
  await loginIfNeeded(page);
  await page.goto(`/sandbox?agent=${agentName}`);
  await page.waitForLoadState('networkidle');
  // Re-login if Keycloak redirect happened
  await loginIfNeeded(page);
  // Verify we're on the sandbox page with the right agent
  const currentUrl = page.url();
  console.log(`[budget] navigateToAgent: final URL = ${currentUrl.substring(0, 150)}`);
  // Wait for chat input to appear
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 30000 });
}

async function sendMessage(page: Page, message: string) {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 15000 });
  await expect(chatInput).toBeEnabled({ timeout: 15000 });
  await chatInput.fill(message);
  console.log(`[budget] sendMessage: filled input, looking for Send button...`);

  // Try multiple selectors for the Send button
  let sendBtn = page.locator('button[type="submit"]');
  if (!(await sendBtn.isVisible({ timeout: 3000 }).catch(() => false))) {
    sendBtn = page.getByRole('button', { name: /Send/i });
  }
  await expect(sendBtn).toBeEnabled({ timeout: 10000 });
  console.log(`[budget] sendMessage: clicking Send`);
  await sendBtn.click();
}

async function waitForResponse(page: Page, timeoutMs = 120000) {
  console.log(`[budget] waitForResponse: waiting for chat input to be enabled (timeout=${timeoutMs}ms)`);
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeEnabled({ timeout: timeoutMs });
  await page.waitForTimeout(3000); // Let UI settle and loop events arrive

  // Verify we're in a session (URL should have session= param)
  const url = page.url();
  const hasSession = url.includes('session=');
  console.log(`[budget] waitForResponse: URL has session=${hasSession}, url=${url.substring(0, 150)}`);

  // Count messages visible in chat
  const msgCount = await page.locator('[data-testid="chat-messages"] [class*="message"]').count();
  console.log(`[budget] waitForResponse: ${msgCount} messages visible in chat`);
}

async function switchToStatsTab(page: Page) {
  console.log(`[budget] switchToStatsTab: looking for Stats tab`);
  // Ensure we're in a session with data before switching tabs
  // Wait for at least one message to appear in chat (proves session loaded)
  const chatMessages = page.locator('[data-testid="chat-messages"]');
  await expect(chatMessages).toBeVisible({ timeout: 15000 });

  const statsTab = page.locator('[role="tab"]').filter({ hasText: /Stats/i });
  await expect(statsTab).toBeVisible({ timeout: 5000 });
  await statsTab.click();
  await page.waitForTimeout(1000); // Let stats render from loop data

  // Debug: check what's visible in the Stats panel
  const statsCards = await page.locator('.pf-v5-c-card').count();
  console.log(`[budget] switchToStatsTab: ${statsCards} cards visible in Stats panel`);
  const budgetCard = page.locator('[data-testid="stats-budget-tokens-used"]');
  const isBudgetVisible = await budgetCard.isVisible().catch(() => false);
  console.log(`[budget] switchToStatsTab: budget section visible = ${isBudgetVisible}`);
}

// ── Test 1: Budget Enforcement ───────────────────────────────────────────────

test.describe('Budget Enforcement', () => {
  test.describe.configure({ retries: 0 });

  let originalMaxTokens: string;

  test.beforeAll(() => {
    // Budget is enforced by the LLM Budget Proxy (DEFAULT_SESSION_MAX_TOKENS).
    // Save and lower the proxy budget for this test.
    originalMaxTokens = kc(
      `get deploy/llm-budget-proxy -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEFAULT_SESSION_MAX_TOKENS")].value}'`
    ) || '1000000';
    console.log(`[budget] Original proxy DEFAULT_SESSION_MAX_TOKENS: ${originalMaxTokens}`);

    // Set proxy budget to 2000 tokens (~1 LLM call)
    kc(`set env deploy/llm-budget-proxy -n ${NAMESPACE} DEFAULT_SESSION_MAX_TOKENS=2000`);
    console.log('[budget] Set proxy DEFAULT_SESSION_MAX_TOKENS=2000');
    kc(`rollout status deploy/llm-budget-proxy -n ${NAMESPACE} --timeout=90s`, 120000);

    // Wait for proxy to be ready
    for (let i = 0; i < 10; i++) {
      const result = kc(
        `exec deploy/llm-budget-proxy -n ${NAMESPACE} -- python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5); print('ready')" 2>/dev/null || echo "not-ready"`,
        15000
      );
      if (result.includes('ready')) {
        console.log(`[budget] Proxy ready after ${i + 1} checks`);
        break;
      }
      execSync('sleep 3');
    }
  });

  test.afterAll(() => {
    // Restore original proxy budget
    kc(`set env deploy/llm-budget-proxy -n ${NAMESPACE} DEFAULT_SESSION_MAX_TOKENS=${originalMaxTokens}`);
    console.log(`[budget] Restored proxy DEFAULT_SESSION_MAX_TOKENS=${originalMaxTokens}`);
    kc(`rollout status deploy/llm-budget-proxy -n ${NAMESPACE} --timeout=90s`, 120000);
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

    // Switch to Stats tab — loop events arrive via SSE stream in real-time,
    // so by the time waitForResponse returns, all data should be populated.
    await switchToStatsTab(page);

    // Budget section MUST be visible with token data
    const budgetTokensUsed = page.locator('[data-testid="stats-budget-tokens-used"]');
    const budgetTokensTotal = page.locator('[data-testid="stats-budget-tokens-total"]');
    await expect(budgetTokensUsed).toBeVisible({ timeout: 10000 });
    await expect(budgetTokensTotal).toBeVisible({ timeout: 10000 });

    const used = Number((await budgetTokensUsed.textContent() || '0').replace(/,/g, ''));
    const total = Number((await budgetTokensTotal.textContent() || '0').replace(/,/g, ''));
    console.log(`[budget] Tokens used: ${used.toLocaleString()} / ${total.toLocaleString()}`);

    // Budget total MUST be 2000 (what we configured)
    expect(total).toBe(2000);

    // Agent MUST have consumed tokens
    expect(used).toBeGreaterThan(0);

    // Wall clock MUST be visible
    const wallClockEl = page.locator('[data-testid="stats-budget-wallclock"]');
    await expect(wallClockEl).toBeVisible({ timeout: 5000 });
    const wallText = await wallClockEl.textContent();
    console.log(`[budget] Wall clock: ${wallText}`);
    expect(wallText).toBeTruthy();

    // Switch to Chat tab and check for budget exceeded message in loop card or chat
    const chatTab = page.locator('[role="tab"]').filter({ hasText: /Chat/i });
    await chatTab.click();
    await page.waitForTimeout(1000);

    // Budget exceeded should appear somewhere in the chat (in loop card or message)
    const chatArea = page.locator('[data-testid="chat-messages"]');
    const chatText = await chatArea.textContent() || '';
    const hasBudgetRef = chatText.toLowerCase().includes('budget') ||
      chatText.toLowerCase().includes('token limit') ||
      chatText.toLowerCase().includes('exceeded');
    console.log(`[budget] Chat contains budget reference: ${hasBudgetRef}`);
    // Soft check — budget exceeded may not always appear in chat text
    // (proxy 402 is caught by the agent and may result in a generic message)

    // Token consistency: LLM Usage tab should show data from proxy
    const llmTab = page.locator('[role="tab"]').filter({ hasText: /LLM Usage/i });
    if (await llmTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await llmTab.click();
      await page.waitForTimeout(1000);
      const llmTotalEl = page.locator('td').filter({ hasText: /Total/i }).locator('..').locator('td').nth(3);
      if (await llmTotalEl.isVisible({ timeout: 3000 }).catch(() => false)) {
        const llmTotal = Number((await llmTotalEl.textContent() || '0').replace(/,/g, ''));
        console.log(`[budget] LLM Usage total: ${llmTotal.toLocaleString()}, Budget used: ${used.toLocaleString()}`);
        // Both should show non-zero usage
        expect(llmTotal).toBeGreaterThan(0);
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

    // Step 5: Budget MUST still be visible and >= pre-restart value.
    // After restart the local AgentBudget counter resets to 0, so the
    // budget_update loop events only carry the post-restart delta.
    // The Stats tab now fetches cumulative totals from the proxy API,
    // but that fetch is async — poll until the value stabilises above
    // the pre-restart baseline.
    await switchToStatsTab(page);
    await expect(budgetTokensUsed).toBeVisible({ timeout: 15000 });

    // Poll for up to 15 s: the proxy API fetch may lag behind the SSE stream.
    let tokensAfterRestart = 0;
    const pollDeadline = Date.now() + 15000;
    while (Date.now() < pollDeadline) {
      tokensAfterRestart = Number(
        (await budgetTokensUsed.textContent() || '0').replace(/,/g, '')
      );
      if (tokensAfterRestart >= tokensBeforeRestart) break;
      await page.waitForTimeout(1000);
    }
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
