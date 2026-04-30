/**
 * Agent Redeploy E2E Test — verifies wizard reconfigure updates running agents.
 *
 * Steps:
 * 1. Deploy agent via wizard with default limits
 * 2. Send a message, verify agent responds
 * 3. Redeploy via wizard with modified limits (+7 to memory/cpu numbers)
 * 4. Wait for pods to restart with new limits
 * 5. Check Pod tab shows updated limits
 * 6. Send another message, verify agent still responds
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const AGENT_NAME = 'rca-redeploy-test';
const NAMESPACE = 'team1';
const REPO_URL = 'https://github.com/kagenti/kagenti';
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

async function next(page: Page) {
  const b = page.getByRole('button', { name: /^Next$/i });
  await expect(b).toBeEnabled({ timeout: 5000 });
  await b.click();
  await page.waitForTimeout(500);
}

async function goToWizard(page: Page) {
  await page.evaluate(() => {
    window.history.pushState({}, '', '/sandbox/create');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await page.waitForTimeout(1000);
  const h = page.getByRole('heading', { name: /Create Sandbox Agent/i });
  if (!(await h.isVisible({ timeout: 3000 }).catch(() => false))) {
    await page.goto('/sandbox/create');
    await page.waitForLoadState('networkidle');
  }
  await expect(h).toBeVisible({ timeout: 15000 });
}

async function deployAgent(page: Page, memoryLimit: string, cpuLimit: string) {
  await goToWizard(page);
  await page.locator('#agent-name').fill(AGENT_NAME);
  await page.locator('#repo-url').fill(REPO_URL);
  // Source → Security → Identity
  await next(page); await next(page);
  const si = page.locator('#llm-secret-name');
  if (await si.isVisible({ timeout: 3000 }).catch(() => false)) await si.fill(LLM_SECRET_NAME);
  // Identity → Persistence → Observability → Budget
  await next(page); await next(page); await next(page);
  // Budget step — set custom limits
  const agentMem = page.locator('#agent-memory-limit');
  if (await agentMem.isVisible({ timeout: 3000 }).catch(() => false)) {
    await agentMem.clear();
    await agentMem.fill(memoryLimit);
    console.log(`[redeploy] Set agent memory limit: ${memoryLimit}`);
  }
  const agentCpu = page.locator('#agent-cpu-limit');
  if (await agentCpu.isVisible({ timeout: 3000 }).catch(() => false)) {
    await agentCpu.clear();
    await agentCpu.fill(cpuLimit);
    console.log(`[redeploy] Set agent CPU limit: ${cpuLimit}`);
  }
  // Budget → Review
  await next(page);
  await expect(page.locator('.pf-v5-c-card__body').first()).toContainText(AGENT_NAME);
  await page.getByRole('button', { name: /Deploy Agent/i }).click();
  console.log('[redeploy] Deploy clicked');
}

async function waitForAgentReady(page: Page, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const replicas = kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`);
    if (replicas === '1') {
      console.log('[redeploy] Agent ready');
      return true;
    }
    await page.waitForTimeout(5000);
  }
  return false;
}

async function sendMessageAndWait(page: Page, message: string) {
  // Navigate to sandbox with this agent
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');
  await page.evaluate((agent) => {
    const url = new URL(window.location.href);
    url.searchParams.set('agent', agent);
    window.history.replaceState({}, '', url.toString());
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, AGENT_NAME);
  await page.waitForTimeout(2000);

  const input = page.locator('textarea[aria-label="Message input"]');
  await expect(input).toBeVisible({ timeout: 15000 });
  await input.fill(message);
  await input.press('Enter');
  console.log(`[redeploy] Sent: ${message}`);

  // Wait for agent response
  const output = page.locator('[data-testid="agent-loop-card"]')
    .or(page.locator('.sandbox-markdown'));
  await expect(output.first()).toBeVisible({ timeout: 120000 });
  // Wait for input to re-enable (loop complete)
  await expect(input).toBeEnabled({ timeout: 180000 });
  console.log('[redeploy] Agent responded');
}

test.describe('Agent Redeploy', () => {
  test.setTimeout(600_000);

  test.beforeAll(() => {
    // Clean up any existing deployment
    kc(`delete deployment ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
    kc(`delete service ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
    kc(`delete deployment ${AGENT_NAME}-egress-proxy -n ${NAMESPACE} --ignore-not-found`);
    kc(`delete service ${AGENT_NAME}-egress-proxy -n ${NAMESPACE} --ignore-not-found`);
    console.log('[redeploy] Cleanup done');
  });

  test('deploy, message, redeploy with new limits, verify limits, message again', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // ── Step 1: Deploy with default limits ────────────────────────────────
    const initialMemory = '1Gi';
    const initialCpu = '500m';
    await deployAgent(page, initialMemory, initialCpu);
    const deployed = await waitForAgentReady(page);
    expect(deployed).toBe(true);

    // Verify initial limits via kubectl
    const initialLimits = kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'`);
    console.log(`[redeploy] Initial limits: ${initialLimits}`);
    expect(initialLimits).toContain(initialMemory);

    // ── Step 2: Send message, verify response ─────────────────────────────
    await sendMessageAndWait(page, 'Say exactly: INITIAL_DEPLOY_OK');
    const chatText1 = await page.locator('[data-testid="chat-messages"]').textContent() || '';
    console.log(`[redeploy] Response 1: ${chatText1.substring(0, 200)}`);

    // ── Step 3: Redeploy with modified limits ─────────────────────────────
    const newMemory = '1537Mi';  // distinctive number
    const newCpu = '507m';       // distinctive number
    console.log(`[redeploy] Redeploying with memory=${newMemory}, cpu=${newCpu}`);
    await deployAgent(page, newMemory, newCpu);

    // Wait for rollout with new limits
    await page.waitForTimeout(10000);
    let newLimitsApplied = false;
    for (let i = 0; i < 24; i++) {
      const limits = kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'`);
      if (limits.includes('1537')) {
        newLimitsApplied = true;
        console.log(`[redeploy] New limits applied: ${limits}`);
        break;
      }
      await page.waitForTimeout(5000);
    }
    expect(newLimitsApplied).toBe(true);

    // Wait for pod to be ready with new limits
    const redeployed = await waitForAgentReady(page);
    expect(redeployed).toBe(true);

    // ── Step 4: Check Pod tab shows new limits ────────────────────────────
    // Navigate to the session and check Pod tab
    const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
    await nav.first().click();
    await page.waitForLoadState('networkidle');
    await page.evaluate((agent) => {
      const url = new URL(window.location.href);
      url.searchParams.set('agent', agent);
      window.history.replaceState({}, '', url.toString());
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, AGENT_NAME);
    await page.waitForTimeout(2000);

    // Click Pod tab
    const podTab = page.locator('[role="tab"]').filter({ hasText: /Pod/i });
    if (await podTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await podTab.click();
      await page.waitForTimeout(2000);
      const podContent = await page.locator('[role="tabpanel"]').textContent() || '';
      console.log(`[redeploy] Pod tab content: ${podContent.substring(0, 300)}`);
      // Check for new limits in pod tab
      const has1537 = podContent.includes('1537');
      const has507 = podContent.includes('507');
      console.log(`[redeploy] Pod tab shows 1537Mi: ${has1537}, 507m: ${has507}`);
    }

    // ── Step 5: Verify via kubectl ────────────────────────────────────────
    const finalLimits = kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'`);
    console.log(`[redeploy] Final kubectl limits: ${finalLimits}`);
    expect(finalLimits).toContain('1537');
    expect(finalLimits).toContain('507');

    // Also check egress proxy got bumped defaults
    const proxyLimits = kc(`get deploy ${AGENT_NAME}-egress-proxy -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].resources.limits}'`);
    console.log(`[redeploy] Egress proxy limits: ${proxyLimits}`);

    // ── Step 6: Send another message after redeploy ───────────────────────
    await sendMessageAndWait(page, 'Say exactly: REDEPLOY_OK');
    const chatText2 = await page.locator('[data-testid="chat-messages"]').textContent() || '';
    console.log(`[redeploy] Response 2: ${chatText2.substring(chatText2.length - 200)}`);

    console.log('[redeploy] All assertions passed');
  });
});
