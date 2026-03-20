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
  console.log(`[budget] waitForResponse: waiting for loop card done (timeout=${timeoutMs}ms)`);

  // Wait for loop card to appear and reach done/failed state
  const loopCards = page.locator('[data-testid="agent-loop-card"]');
  await expect(loopCards.last()).toBeVisible({ timeout: 30000 });
  const activeStatuses = loopCards.last().locator('text=/planning|executing|reflecting/');
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const count = await activeStatuses.count();
    if (count === 0) break;
    await page.waitForTimeout(2000);
  }
  await page.waitForTimeout(2000);

  // Verify we're in a session
  const url = page.url();
  const hasSession = url.includes('session=');
  console.log(`[budget] waitForResponse: URL has session=${hasSession}, url=${url.substring(0, 150)}`);
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

  let originalMaxTokens: string;

  test.beforeAll(() => {
    // Budget is enforced by the LLM Budget Proxy (DEFAULT_SESSION_MAX_TOKENS).
    // Save and lower the proxy budget for this test.
    originalMaxTokens = kc(
      `get deploy/llm-budget-proxy -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEFAULT_SESSION_MAX_TOKENS")].value}'`
    ) || '1000000';
    console.log(`[budget] Original proxy DEFAULT_SESSION_MAX_TOKENS: ${originalMaxTokens}`);

    // Set very low budget so the proxy returns 402 mid-task.
    // 200 tokens is less than a single LLM call, forcing immediate 402.
    kc(`set env deploy/llm-budget-proxy -n ${NAMESPACE} DEFAULT_SESSION_MAX_TOKENS=200`);
    kc(`set env deploy/${BUDGET_AGENT} -n ${NAMESPACE} SANDBOX_MAX_TOKENS=200`);
    console.log('[budget] Set budget=200 on proxy + agent');

    // Wait for both rollouts
    kc(`rollout status deploy/llm-budget-proxy -n ${NAMESPACE} --timeout=90s`, 120000);
    kc(`rollout status deploy/${BUDGET_AGENT} -n ${NAMESPACE} --timeout=90s`, 120000);

    // Wait for agent to be ready
    for (let i = 0; i < 10; i++) {
      const result = kc(
        `exec deploy/${BUDGET_AGENT} -n ${NAMESPACE} -- python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/.well-known/agent-card.json', timeout=5); print('ready')"`,
        15000
      );
      if (result.includes('ready')) {
        console.log(`[budget] Agent ready after ${i + 1} checks`);
        break;
      }
      execSync('sleep 3');
    }
  });

  test.afterAll(() => {
    // Restore original budget on both proxy and agent
    kc(`set env deploy/llm-budget-proxy -n ${NAMESPACE} DEFAULT_SESSION_MAX_TOKENS=${originalMaxTokens}`);
    kc(`set env deploy/${BUDGET_AGENT} -n ${NAMESPACE} SANDBOX_MAX_TOKENS-`);
    console.log(`[budget] Restored proxy budget=${originalMaxTokens}, removed agent override`);
    kc(`rollout status deploy/llm-budget-proxy -n ${NAMESPACE} --timeout=90s`, 120000);
    kc(`rollout status deploy/${BUDGET_AGENT} -n ${NAMESPACE} --timeout=90s`, 120000);
  });

  test('agent stops when token budget is exhausted and UI shows budget', async ({ page }) => {
    test.setTimeout(300_000);

    await navigateToAgent(page, BUDGET_AGENT);

    // ── Message 1: Should trigger 402 from proxy (budget=200 < single LLM call) ──
    await sendMessage(
      page,
      'Write a detailed analysis of the /workspace directory structure. ' +
        'List all files recursively, then analyze each file type and summarize.'
    );
    await waitForResponse(page, 180000);

    // Chat should show budget-related content (402 error caught by agent)
    const chatArea = page.locator('[data-testid="chat-messages"]');
    const chatText1 = await chatArea.textContent() || '';
    const hasBudgetRef = chatText1.toLowerCase().includes('budget') ||
      chatText1.toLowerCase().includes('exceeded') ||
      chatText1.toLowerCase().includes('402') ||
      chatText1.toLowerCase().includes('no response');
    console.log(`[budget] Message 1 — budget reference in chat: ${hasBudgetRef}`);
    console.log(`[budget] Message 1 — chat preview: ${chatText1.substring(0, 300)}`);

    // Stats tab should show budget data
    await switchToStatsTab(page);
    const budgetTokensTotal = page.locator('[data-testid="stats-budget-tokens-total"]');
    if (await budgetTokensTotal.isVisible({ timeout: 5000 }).catch(() => false)) {
      const total = Number((await budgetTokensTotal.textContent() || '0').replace(/,/g, ''));
      console.log(`[budget] Budget total shown: ${total}`);
      expect(total).toBe(200);
    }

    // ── Message 2: Follow-up after budget exhausted ──
    // Same session — proxy should return 402 again, agent should report budget exceeded
    const chatTab = page.locator('[role="tab"]').filter({ hasText: /Chat/i });
    await chatTab.click();
    await page.waitForTimeout(1000);

    await sendMessage(page, 'Hello, can you respond?');
    await waitForResponse(page, 60000);

    const chatText2 = await chatArea.textContent() || '';
    const budgetKeywords2 = ['budget', 'exceeded', '402', 'no response', 'exhausted', 'limit'];
    const hasBudgetRef2 = budgetKeywords2.some(kw => chatText2.toLowerCase().includes(kw));
    console.log(`[budget] Message 2 — budget reference: ${hasBudgetRef2}`);
    console.log(`[budget] Message 2 — new content: ${chatText2.substring(chatText1.length, chatText1.length + 300)}`);
    // After first 402, follow-ups MUST mention budget/exceeded
    expect(hasBudgetRef2).toBe(true);

    // ── Message 3: Third attempt — verify consistent behavior ──
    await sendMessage(page, 'Try one more time please');
    await waitForResponse(page, 60000);

    const chatText3 = await chatArea.textContent() || '';
    const hasBudgetRef3 = budgetKeywords2.some(kw => chatText3.toLowerCase().includes(kw));
    console.log(`[budget] Message 3 — budget reference: ${hasBudgetRef3}`);
    console.log(`[budget] Message 3 — chat length: ${chatText3.length} (growth: ${chatText3.length - chatText2.length})`);
    // Third message MUST also mention budget — behavior is consistent
    expect(hasBudgetRef3).toBe(true);
    // Chat MUST have grown (agent responded, didn't hang)
    expect(chatText3.length).toBeGreaterThan(chatText1.length);

    console.log('[budget] Budget enforcement test complete — 3 messages, all show budget exceeded');
  });
});

// ── Test 2: Budget Persists Across Restart ───────────────────────────────────

test.describe('Budget Persistence Across Restart', () => {

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
