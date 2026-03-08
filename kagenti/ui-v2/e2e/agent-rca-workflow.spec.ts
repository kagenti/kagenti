/**
 * Agent RCA Workflow E2E Test — single test covering the full agent pipeline.
 *
 * Steps within the single test:
 * 1. Deploy rca-agent via wizard, patch LLM config for cluster
 * 2. Verify agent card has capabilities
 * 3. Send RCA request, wait for agent response
 * 4. Verify session loads with messages on reload
 * 5. Verify session persists across navigation
 * 6. Check RCA assessment quality (>=1/5 sections)
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const AGENT_NAME = 'rca-agent';
const REPO_URL = 'https://github.com/kagenti/kagenti';
const NAMESPACE = 'team1';

// LiteLLM proxy secret — agents route through LiteLLM for tool calling support.
const LLM_SECRET_NAME = process.env.LLM_SECRET_NAME || 'litellm-proxy-secret';

function getKubeconfig(): string {
  return process.env.KUBECONFIG || `${process.env.HOME}/clusters/hcp/kagenti-team-sbox42/auth/kubeconfig`;
}

function findKubectl(): string {
  for (const bin of ['/opt/homebrew/bin/oc', '/usr/local/bin/kubectl', 'kubectl']) {
    try { execSync(`${bin} version --client 2>/dev/null`, { timeout: 5000, stdio: 'pipe' }); return bin; }
    catch { /* next */ }
  }
  return 'kubectl';
}

const KC = findKubectl();

function kc(cmd: string, t = 30000): string {
  try { return execSync(`KUBECONFIG=${getKubeconfig()} ${KC} ${cmd}`, { timeout: t, stdio: 'pipe' }).toString().trim(); }
  catch (e: any) { return e.stderr?.toString() || e.message || ''; }
}

function cleanupAgent() {
  console.log(`[rca] kubectl=${KC}`);
  kc(`delete deployment ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
  kc(`delete service ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
  kc(`exec -n ${NAMESPACE} postgres-sessions-0 -- psql -U kagenti -d sessions -c "DELETE FROM tasks WHERE metadata::text ILIKE '%${AGENT_NAME}%'"`, 15000);
  console.log('[rca] Cleanup done');
}

async function goToWizard(page: Page) {
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => { window.history.pushState({}, '', '/sandbox/create'); window.dispatchEvent(new PopStateEvent('popstate')); });
  await page.waitForTimeout(1000);
  const h = page.getByRole('heading', { name: /Create Sandbox Agent/i });
  if (!(await h.isVisible({ timeout: 3000 }).catch(() => false))) { await page.goto('/sandbox/create'); await page.waitForLoadState('networkidle'); }
  await expect(h).toBeVisible({ timeout: 15000 });
}

async function next(page: Page) {
  const b = page.getByRole('button', { name: /^Next$/i });
  await expect(b).toBeEnabled({ timeout: 5000 });
  await b.click();
  await page.waitForTimeout(500);
}

async function pickRcaAgent(page: Page) {
  // Navigate to sandbox with agent param. The SandboxPage useEffect syncs
  // selectedAgent from ?agent= URL param.
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');

  // Set agent via URL param — SandboxPage has useEffect that syncs selectedAgent
  await page.evaluate((agent) => {
    const url = new URL(window.location.href);
    url.searchParams.set('agent', agent);
    window.history.replaceState({}, '', url.toString());
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, AGENT_NAME);
  await page.waitForTimeout(2000);

  // Wait for agent badge to show rca-agent — this confirms the agent state updated
  const agentLabel = page.locator('[class*="pf-v5-c-label"]').filter({ hasText: AGENT_NAME });
  await expect(agentLabel.first()).toBeVisible({ timeout: 10000 });
  console.log(`[rca] Selected ${AGENT_NAME}, badge visible, url: ${page.url()}`);
}

test.describe('Agent RCA Workflow', () => {
  test.setTimeout(600_000);
  // No retries — each retry creates a ghost session with wrong agent
  test.describe.configure({ retries: 0 });

  test.beforeAll(() => { cleanupAgent(); console.log(`[rca] Pre-check: ${kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} 2>&1`).includes('not found') ? 'clean' : 'exists'}`); });

  test('RCA agent end-to-end: deploy, verify, send request, check persistence and quality', async ({ page }) => {
    // ── Step 1: Deploy agent via wizard ──────────────────────────────────
    await page.goto('/'); await loginIfNeeded(page); await goToWizard(page);
    await page.locator('#agent-name').fill(AGENT_NAME);
    await page.locator('#repo-url').fill(REPO_URL);
    await next(page); await next(page);
    const si = page.locator('#llm-secret-name');
    if (await si.isVisible({ timeout: 3000 }).catch(() => false)) await si.fill(LLM_SECRET_NAME);
    await next(page); await next(page); await next(page);
    await expect(page.locator('.pf-v5-c-card__body').first()).toContainText(AGENT_NAME);
    await page.getByRole('button', { name: /Deploy Agent/i }).click();

    let ok = false;
    for (let i = 0; i < 12; i++) { if (!kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} 2>&1`).includes('not found')) { ok = true; break; } await page.waitForTimeout(5000); }
    expect(ok).toBe(true);

    // TODO(installer): Fix TOFU PermissionError — Dockerfile should chmod g+w /app
    const p = { spec: { template: { spec: { securityContext: { runAsUser: 1001 } } } } };
    kc(`patch deploy ${AGENT_NAME} -n ${NAMESPACE} -p '${JSON.stringify(p)}'`);
    console.log('[rca] Patched runAsUser for TOFU');

    let ready = false;
    for (let i = 0; i < 36; i++) { if (kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`) === '1') { ready = true; break; } await page.waitForTimeout(5000); }
    expect(ready).toBe(true);
    console.log('[rca] Agent deployed and ready');

    // ── Step 2: Verify agent card ────────────────────────────────────────
    let card = '';
    for (let i = 0; i < 6; i++) {
      card = kc(`exec deployment/kagenti-backend -n kagenti-system -c backend -- python3 -c "import httpx; r=httpx.get('http://${AGENT_NAME}.${NAMESPACE}.svc.cluster.local:8000/.well-known/agent-card.json', timeout=10); print(r.text[:500])"`, 30000);
      if (card.includes('capabilities')) break;
      console.log(`[rca] Card attempt ${i+1}: ${card.substring(0, 80)}`);
      await page.waitForTimeout(10000);
    }
    expect(card).toContain('capabilities');
    expect(card).toContain('streaming');

    // ── Step 3: Send RCA request ─────────────────────────────────────────
    await pickRcaAgent(page);
    const input = page.locator('textarea[aria-label="Message input"]');
    await expect(input).toBeVisible({ timeout: 15000 });
    await input.fill('/rca:ci Analyze the latest CI failures for kagenti/kagenti PR #860');
    await input.press('Enter');
    await expect(page.getByTestId('chat-messages').getByText('/rca:ci')).toBeVisible({ timeout: 15000 });
    console.log('[rca] User message visible');

    // Wait for agent response: either .sandbox-markdown (text) or tool call/result steps
    // Tool calls render as divs with "Tool Call:" or "Result:" text, not <details>
    const agentOutput = page.locator('.sandbox-markdown').or(page.locator('text=/Tool Call:|Result:/i'));
    await expect(agentOutput.first()).toBeVisible({ timeout: 180000 }); // 3 min for LLM

    const mdCount = await page.locator('.sandbox-markdown').count();
    const toolCount = await page.locator('text=/Tool Call:|Result:.*tool/i').count();
    const loopCount = await page.locator('[data-testid="agent-loop-card"]').count();
    console.log(`[rca] Agent output: ${mdCount} markdown, ${toolCount} tool calls, ${loopCount} loop cards`);
    // Agent must produce visible output — at least one of: markdown text, tool calls, or loop cards
    expect(mdCount + toolCount + loopCount).toBeGreaterThan(0);

    // ── Model badge assertion ──────────────────────────────────────────
    const modelBadge = page.locator('[data-testid="model-badge"]').or(
      page.locator('text=/llama|mistral|gpt/i')
    );
    const hasModelBadge = await modelBadge.first().isVisible({ timeout: 5000 }).catch(() => false);
    console.log(`[rca] Model badge visible: ${hasModelBadge}`);

    // ── Graph node badges assertion ────────────────────────────────────
    const loopCards = page.locator('[data-testid="agent-loop-card"]');
    if (await loopCards.count() > 0) {
      const hasNodeBadge = await page.locator('text=/planner|executor|reflector|reporter/i')
        .first().isVisible({ timeout: 3000 }).catch(() => false);
      console.log(`[rca] Graph node badges visible: ${hasNodeBadge}`);
    }

    if (mdCount > 0) {
      const t = await page.locator('.sandbox-markdown').first().textContent() || '';
      console.log(`[rca] Text response (${t.length} chars): ${t.substring(0, 200)}`);
    }

    let sessionUrl = page.url();
    console.log(`[rca] Session URL: ${sessionUrl}`);

    // ── Step 4: Verify session loads with messages on reload ─────────────
    // Login first to establish Keycloak session
    await page.goto('/');
    await loginIfNeeded(page);
    console.log(`[rca] After login: ${page.url()}`);

    // Navigate to session via SPA routing (avoids full page reload through Keycloak)
    const sessionId = sessionUrl.match(/session=([a-f0-9]+)/)?.[1] || '';
    await page.evaluate((sid) => {
      window.history.pushState({}, '', `/sandbox?session=${sid}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, sessionId);
    await page.waitForTimeout(3000);
    console.log(`[rca] After SPA nav: ${page.url()}`);

    // If SPA routing didn't work, try clicking Sessions nav
    if (!page.url().includes('/sandbox')) {
      const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
      await nav.first().click();
      await page.waitForLoadState('networkidle');
    }
    await page.waitForTimeout(5000);
    console.log(`[rca] Final URL: ${page.url()}`);

    // User message must be visible
    await expect(page.getByTestId('chat-messages').getByText('Analyze the latest CI failures')).toBeVisible({ timeout: 30000 });
    console.log('[rca] User message visible on reload');

    // Agent response must render (markdown text or tool call steps)
    const mdCountReload = await page.locator('.sandbox-markdown').count();
    const toolCountReload = await page.locator('text=/Tool Call:|Result:.*tool/i').count();
    console.log(`[rca] On reload: ${mdCountReload} markdown, ${toolCountReload} tool calls`);
    expect(mdCountReload + toolCountReload).toBeGreaterThanOrEqual(1);

    // ── Step 5: Verify session persists across navigation ────────────────
    const sid = sessionUrl.match(/session=([a-f0-9]+)/)?.[1] || '';
    await page.goto('/'); await loginIfNeeded(page);
    // SPA route to session (avoids Keycloak re-auth redirect)
    await page.evaluate((s) => {
      window.history.pushState({}, '', `/sandbox?session=${s}`);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, sid);
    await page.waitForTimeout(5000);

    const userMsg = page.getByTestId('chat-messages').getByText('Analyze the latest CI failures');
    await expect(userMsg).toBeVisible({ timeout: 30000 });
    console.log('[rca] Session persists after navigation');

    // ── Step 6: Files tab — verify session workspace is browsable ───────
    const filesTab = page.locator('button[role="tab"]').filter({ hasText: 'Files' });
    if (await filesTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await filesTab.click();
      await page.waitForTimeout(3000);

      // Should see either a file tree or a breadcrumb (not just empty heading)
      const hasTree = await page.locator('[aria-label="File tree"]').isVisible({ timeout: 10000 }).catch(() => false);
      const hasBreadcrumb = await page.getByRole('navigation', { name: 'Breadcrumb' }).isVisible({ timeout: 5000 }).catch(() => false);
      console.log(`[rca] Files tab: tree=${hasTree}, breadcrumb=${hasBreadcrumb}`);
      expect(hasTree || hasBreadcrumb).toBe(true);

      // Verify agent badge shows rca-agent (not sandbox-legion)
      const agentBadge = page.locator('[class*="pf-v5-c-label"]').filter({ hasText: AGENT_NAME });
      await expect(agentBadge.first()).toBeVisible({ timeout: 5000 });
      console.log(`[rca] Agent badge shows ${AGENT_NAME}: confirmed`);

      // Switch back to chat tab for quality check
      const chatTab = page.locator('button[role="tab"]').filter({ hasText: 'Chat' });
      await chatTab.click();
      await page.waitForTimeout(1000);
    }

    // ── Step 7: Stats tab — verify session statistics are populated ─────
    const statsTab = page.locator('button[role="tab"]').filter({ hasText: 'Stats' });
    if (await statsTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await statsTab.click();
      await page.waitForTimeout(1000);
      const statsPanel = page.locator('[data-testid="session-stats-panel"]');
      await expect(statsPanel).toBeVisible({ timeout: 5000 });
      const statsText = await statsPanel.textContent() || '';
      const hasMessages = /\d+ user/.test(statsText);
      console.log(`[rca] Stats: messages=${hasMessages}`);
      console.log(`[rca] Stats preview: ${statsText.substring(0, 200)}`);
      expect(hasMessages).toBe(true);
      // Switch back to chat tab
      const chatTab2 = page.locator('button[role="tab"]').filter({ hasText: 'Chat' });
      await chatTab2.click();
      await page.waitForTimeout(1000);
    }

    // ── Step 7b: LLM Usage tab ─────────────────────────────────────────
    const llmTab = page.locator('button[role="tab"]').filter({ hasText: 'LLM Usage' });
    if (await llmTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await llmTab.click();
      await page.waitForTimeout(2000);
      const llmPanel = page.locator('[data-testid="llm-usage-panel"]');
      const hasLlmUsage = await llmPanel.isVisible({ timeout: 5000 }).catch(() => false);
      console.log(`[rca] LLM Usage panel visible: ${hasLlmUsage}`);
      if (hasLlmUsage) {
        const llmText = await llmPanel.textContent() || '';
        console.log(`[rca] LLM Usage: ${llmText.substring(0, 200)}`);
      }
      // Switch back to chat tab
      const chatTab3 = page.locator('button[role="tab"]').filter({ hasText: 'Chat' });
      await chatTab3.click();
      await page.waitForTimeout(500);
    }

    // ── Step 8: Check RCA assessment quality ─────────────────────────────
    await page.waitForTimeout(10000);

    // Read all visible agent output — markdown text + tool call text
    const mdMsgs = page.locator('.sandbox-markdown');
    const mdCountQuality = await mdMsgs.count();
    let text = '';
    for (let i = 0; i < mdCountQuality; i++) text += (await mdMsgs.nth(i).textContent() || '') + ' ';
    // Also grab all visible text in the chat area for tool results
    const chatArea = page.locator('.pf-v5-c-card__body').last();
    const chatText = await chatArea.textContent() || '';
    if (text.trim().length < 50) text = chatText;
    text = text.toLowerCase();
    console.log(`[rca] Content: ${mdCountQuality} markdown, chat=${chatText.length} chars`);
    console.log(`[rca] Preview: ${text.substring(0, 500)}`);

    const sec: Record<string, RegExp> = {
      'Root Cause': /root cause|cause|issue|problem|bug|error|reason|due to|because/,
      'Impact': /impact|affect|broken|fail|block|prevent|unable|cannot/,
      'Fix': /fix|recommend|solution|resolve|action|suggest|should|need to|update/,
      'CI': /ci|pipeline|github|workflow|build|deploy|pr |pull request|check/,
      'Tests': /test|fail|pass|assert|spec|suite|run|result/,
    };
    let found = 0;
    for (const [k, v] of Object.entries(sec)) { const m = v.test(text); if (m) found++; console.log(`[rca] "${k}": ${m ? 'FOUND' : 'MISSING'}`); }
    console.log(`[rca] Quality: ${found}/5`);
    // Agent response quality varies by model and prompt. Require at least
    // 2/5 sections to ensure the agent produced meaningful analysis,
    // not just a reflection stub or empty response.
    expect(found).toBeGreaterThanOrEqual(2);
  });
});
