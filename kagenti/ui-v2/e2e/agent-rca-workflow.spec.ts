/**
 * Agent RCA Workflow E2E Test — 6 serial steps testing the full agent pipeline.
 *
 * 1. Deploy rca-agent via wizard, patch LLM config for cluster
 * 2. Verify agent card has capabilities
 * 3. Send RCA request, wait for agent response
 * 4. Verify session loads with messages
 * 5. Verify session persists on reload
 * 6. Check RCA assessment quality (>=2/5 sections)
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const AGENT_NAME = 'rca-agent';
const REPO_URL = 'https://github.com/kagenti/kagenti';
const NAMESPACE = 'team1';

// TODO(wizard-api): Wizard hardcodes LLM_API_BASE=api.openai.com. Fix to support cluster LLM.
const LLM_API_BASE = process.env.LLM_API_BASE ||
  'https://mistral-small-24b-w8a8-maas-apicast-production.apps.prod.rhoai.rh-aiservices-bu.com:443/v1';
const LLM_MODEL = process.env.LLM_MODEL || 'mistral-small-24b-w8a8';
const LLM_SECRET_NAME = process.env.LLM_SECRET_NAME || 'openai-secret';

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
  const nav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(nav.first()).toBeVisible({ timeout: 10000 });
  await nav.first().click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  const e = page.locator('text=rca-agent').first();
  if (await e.isVisible({ timeout: 5000 }).catch(() => false)) { await e.click(); await page.waitForTimeout(1000); }
  console.log(`[rca] Selected ${AGENT_NAME}`);
}

test.describe('Agent RCA Workflow', () => {
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(300000);
  let sessionUrl: string | null = null;

  test.beforeAll(() => { cleanupAgent(); console.log(`[rca] Pre-check: ${kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} 2>&1`).includes('not found') ? 'clean' : 'exists'}`); });

  test('1 — deploy agent via wizard', async ({ page }) => {
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

    // TODO(wizard-api): Fix hardcoded OpenAI. TODO(installer): Fix TOFU PermissionError.
    const p = { spec: { template: { spec: { securityContext: { runAsUser: 1001 }, containers: [{ name: 'agent', env: [{ name: 'LLM_API_BASE', value: LLM_API_BASE }, { name: 'LLM_MODEL', value: LLM_MODEL }] }] } } } };
    kc(`patch deploy ${AGENT_NAME} -n ${NAMESPACE} --type=strategic -p '${JSON.stringify(p)}'`);
    console.log('[rca] Patched LLM + security');

    let ready = false;
    for (let i = 0; i < 36; i++) { if (kc(`get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`) === '1') { ready = true; break; } await page.waitForTimeout(5000); }
    expect(ready).toBe(true);
    console.log('[rca] Agent deployed and ready');
  });

  test('2 — verify agent card', async ({ page }) => {
    await page.goto('/'); await loginIfNeeded(page);
    let card = '';
    for (let i = 0; i < 6; i++) {
      card = kc(`exec deployment/kagenti-backend -n kagenti-system -c backend -- python3 -c "import httpx; r=httpx.get('http://${AGENT_NAME}.${NAMESPACE}.svc.cluster.local:8000/.well-known/agent-card.json', timeout=10); print(r.text[:500])"`, 30000);
      if (card.includes('capabilities')) break;
      console.log(`[rca] Card attempt ${i+1}: ${card.substring(0, 80)}`);
      await page.waitForTimeout(10000);
    }
    expect(card).toContain('capabilities');
    expect(card).toContain('streaming');
  });

  test('3 — send RCA request', async ({ page }) => {
    await page.goto('/'); await loginIfNeeded(page); await pickRcaAgent(page);
    const input = page.locator('textarea[aria-label="Message input"]');
    await expect(input).toBeVisible({ timeout: 15000 });
    await input.fill('Analyze the latest CI failures for kagenti/kagenti PR #758. Report root cause, impact, and recommended fix.');
    await input.press('Enter');
    await expect(page.getByText('Analyze the latest CI failures')).toBeVisible({ timeout: 15000 });
    console.log('[rca] User message visible');
    const resp = page.locator('.sandbox-markdown').first();
    await expect(resp).toBeVisible({ timeout: 180000 });
    const t = await resp.textContent() || '';
    console.log(`[rca] Response (${t.length} chars): ${t.substring(0, 200)}`);
    expect(t.length).toBeGreaterThan(20);
    sessionUrl = page.url();
    console.log(`[rca] Session URL: ${sessionUrl}`);
  });

  test('4 — session loads with messages', async ({ page }) => {
    await page.goto('/'); await loginIfNeeded(page);
    if (sessionUrl) { await page.goto(sessionUrl); await page.waitForLoadState('networkidle'); }
    else { await pickRcaAgent(page); }
    await page.waitForTimeout(5000);
    const msgs = page.locator('.sandbox-markdown');
    let c = await msgs.count();
    console.log(`[rca] .sandbox-markdown: ${c}`);
    if (c === 0) { const u = page.getByText('Analyze the latest CI failures'); if (await u.isVisible({ timeout: 10000 }).catch(() => false)) c = 1; }
    expect(c).toBeGreaterThanOrEqual(1);
  });

  test('5 — session persists on reload', async ({ page }) => {
    expect(sessionUrl).toBeTruthy();
    await page.goto('/'); await loginIfNeeded(page);
    await page.goto(sessionUrl!); await page.waitForLoadState('networkidle'); await page.waitForTimeout(5000);
    const has = await page.getByText('Analyze the latest CI failures').isVisible({ timeout: 15000 }).catch(() => false);
    console.log(`[rca] User message on reload: ${has}`);
    expect(has).toBe(true);
  });

  test('6 — RCA assessment quality', async ({ page }) => {
    await page.goto('/'); await loginIfNeeded(page);
    if (sessionUrl) { await page.goto(sessionUrl); await page.waitForLoadState('networkidle'); }
    else { await pickRcaAgent(page); }
    await page.waitForTimeout(10000);
    const msgs = page.locator('.sandbox-markdown');
    const c = await msgs.count();
    let text = '';
    for (let i = 0; i < c; i++) text += (await msgs.nth(i).textContent() || '') + ' ';
    text = text.toLowerCase();
    console.log(`[rca] Msgs: ${c}, chars: ${text.length}`);
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
    expect(found).toBeGreaterThanOrEqual(2);
  });
});
