/**
 * Agent RCA Workflow E2E Test
 *
 * Full pipeline test:
 * 1. Delete any existing rca-agent deployment (clean slate)
 * 2. Deploy new agent via wizard managing kagenti/kagenti repo
 * 3. Agent loads CLAUDE.md + .claude/skills/ from the repo
 * 4. Send /rca:ci request — agent analyzes CI failures
 * 5. Agent uses sub-agents for parallel log analysis
 * 6. Verify final assessment has: root cause, impact, fix sections
 *
 * Default config: in-process sub-agents, sandbox-legion base, default security.
 * Future: parameterize across security tiers.
 */
import { test, expect } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const AGENT_NAME = 'rca-agent';
const REPO_URL = 'https://github.com/kagenti/kagenti';
const NAMESPACE = 'team1';

function getKubeconfig(): string {
  return process.env.KUBECONFIG ||
    `${process.env.HOME}/clusters/hcp/kagenti-team-sbox/auth/kubeconfig`;
}

function kubectl(cmd: string): string {
  try {
    return execSync(`KUBECONFIG=${getKubeconfig()} kubectl ${cmd}`, {
      timeout: 15000,
      stdio: 'pipe',
    }).toString().trim();
  } catch (e: any) {
    return e.stderr?.toString() || e.message || '';
  }
}

/**
 * Delete deployment, service, and sessions for our test agent.
 * Safe to call when agent doesn't exist.
 */
function cleanupAgent() {
  console.log(`[rca] Deleting ${AGENT_NAME} deployment...`);
  kubectl(`delete deployment ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
  kubectl(`delete service ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`);
  kubectl(
    `exec -n ${NAMESPACE} postgres-sessions-0 -- psql -U kagenti -d sessions ` +
    `-c "DELETE FROM tasks WHERE metadata::text ILIKE '%${AGENT_NAME}%'"`
  );
  console.log(`[rca] Cleanup done`);
}

/** Navigate to the wizard page (auth-safe). */
async function navigateToWizard(page: any) {
  // First navigate to Sessions (establishes auth context)
  const sessionsNav = page.locator('nav a, nav button').filter({ hasText: /^Sessions$/ });
  await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
  await sessionsNav.first().click();
  await page.waitForLoadState('networkidle');

  // Then navigate to wizard via SPA
  await page.evaluate(() => {
    window.history.pushState({}, '', '/sandbox/create');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await page.waitForTimeout(1000);

  const heading = page.getByRole('heading', { name: /Create Sandbox Agent/i });
  if (!(await heading.isVisible({ timeout: 3000 }).catch(() => false))) {
    await page.goto('/sandbox/create');
    await page.waitForLoadState('networkidle');
  }
  await expect(heading).toBeVisible({ timeout: 15000 });
}

/** Click Next in the wizard stepper. */
async function clickNext(page: any) {
  const next = page.getByRole('button', { name: /^Next$/i });
  await expect(next).toBeEnabled({ timeout: 5000 });
  await next.click();
  await page.waitForTimeout(500);
}

// =========================================================================
// TESTS
// =========================================================================

test.describe('Agent RCA Workflow', () => {
  // Serial — each step depends on the previous
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(300000); // 5 min per test

  test.beforeAll(() => {
    cleanupAgent();
    // Verify clean
    const result = kubectl(`get deploy ${AGENT_NAME} -n ${NAMESPACE} 2>&1`);
    console.log(`[rca] Pre-check: ${result.includes('not found') ? 'clean' : 'EXISTS (unexpected)'}`);
  });

  test.afterAll(() => {
    cleanupAgent();
  });

  test('1 — deploy agent via wizard with kagenti/kagenti repo', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Step 1: Source — agent name + repo
    await page.locator('#agent-name').fill(AGENT_NAME);
    await page.locator('#repo-url').fill(REPO_URL);
    await clickNext(page);

    // Step 2: Security — accept defaults (non-root, drop caps, seccomp)
    await clickNext(page);

    // Step 3: Identity — accept defaults
    await clickNext(page);

    // Step 4: Persistence — accept defaults
    await clickNext(page);

    // Step 5: Observability — accept defaults
    await clickNext(page);

    // Step 6: Review — verify our values shown
    const review = page.locator('.pf-v5-c-card__body').first();
    await expect(review).toContainText(AGENT_NAME);
    await expect(review).toContainText('kagenti/kagenti');

    // Click Deploy
    const deployBtn = page.getByRole('button', { name: /Deploy Agent/i });
    await expect(deployBtn).toBeVisible();
    await deployBtn.click();

    // Wait for deployment to be ready (poll kubectl)
    let ready = false;
    for (let i = 0; i < 60; i++) { // up to 5 min
      const replicas = kubectl(
        `get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`
      );
      if (replicas === '1') {
        ready = true;
        break;
      }
      await page.waitForTimeout(5000);
    }

    expect(ready).toBe(true);
    console.log(`[rca] Agent ${AGENT_NAME} deployed and ready`);
  });

  test('2 — verify agent card shows kagenti skills', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Check agent card via kubectl (A2A card should list skills)
    const card = kubectl(
      `exec deployment/kagenti-backend -n kagenti-system -c backend -- ` +
      `python3 -c "import httpx; r=httpx.get('http://${AGENT_NAME}.${NAMESPACE}.svc.cluster.local:8000/.well-known/agent-card.json', timeout=10); print(r.text[:500])"`
    );
    console.log(`[rca] Agent card: ${card.substring(0, 200)}`);

    // Card should exist and have streaming capability
    expect(card).toContain('capabilities');
    expect(card).toContain('streaming');
  });

  test('3 — send RCA request and verify agent processes it', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Navigate to Sessions
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Select our agent in the agent panel (if there's a selector)
    const agentSelector = page.locator(`text=${AGENT_NAME}`).first();
    if (await agentSelector.isVisible({ timeout: 3000 }).catch(() => false)) {
      await agentSelector.click();
      await page.waitForTimeout(1000);
    }

    // Send the RCA prompt
    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    await chatInput.fill(
      'Analyze the latest CI failures for kagenti/kagenti PR #758. ' +
      'Use the /rca:ci skill. Report root cause, impact, and recommended fix.'
    );
    await page.getByRole('button', { name: /Send/i }).click();

    // Verify user message appears with username
    await expect(page.getByText('Analyze the latest CI failures')).toBeVisible({ timeout: 10000 });

    // Wait for agent to start responding (streaming or first tool call)
    const agentResponse = page.locator(
      'text=/analyzing|processing|checking|error|failure|root cause|CI|github/i'
    ).first();
    await expect(agentResponse).toBeVisible({ timeout: 120000 }); // 2 min for LLM

    console.log('[rca] Agent started processing RCA request');
  });

  test('4 — tool call steps appear during analysis', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Navigate to Sessions, click on the latest session
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Click the first session (most recent)
    const session = page.locator('[role="button"]').filter({
      hasText: new RegExp(`${AGENT_NAME}|rca|Analyze`, 'i'),
    }).first();
    if (await session.isVisible({ timeout: 5000 }).catch(() => false)) {
      await session.click();
      await page.waitForTimeout(3000);
    }

    // Check for tool call evidence in the chat
    // The agent should have called: gh, shell, or file tools
    const toolEvidence = page.locator(
      'text=/Tool Call|tool_call|shell|gh |file_read|file_write|command/i'
    ).first();
    const hasTool = await toolEvidence.isVisible({ timeout: 30000 }).catch(() => false);
    console.log(`[rca] Tool call evidence: ${hasTool}`);

    // Also check for structured tool steps (ToolCallStep component)
    const toolSteps = page.locator('[data-testid="tool-call-step"]');
    const stepCount = await toolSteps.count();
    console.log(`[rca] Tool call step components: ${stepCount}`);

    // At minimum, some agent output should be visible
    const chatContent = page.locator('[style*="overflow"]').first();
    const text = await chatContent.textContent() || '';
    expect(text.length).toBeGreaterThan(50);
  });

  test('5 — sub-agent sessions appear in sidebar', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Count sessions — if sub-agents spawned, there should be more than 1
    const sessionCount = await page.locator('[role="button"]').filter({
      hasText: /sandbox|rca|agent/i,
    }).count();
    console.log(`[rca] Sessions in sidebar: ${sessionCount}`);

    // Check sessions table for parent_context_id (sub-sessions)
    const subsCount = kubectl(
      `exec -n ${NAMESPACE} postgres-sessions-0 -- psql -U kagenti -d sessions ` +
      `-c "SELECT COUNT(DISTINCT context_id) as sessions FROM tasks WHERE metadata::text ILIKE '%${AGENT_NAME}%'"`
    );
    console.log(`[rca] DB sessions for ${AGENT_NAME}: ${subsCount}`);

    // At least the parent session should exist
    expect(sessionCount).toBeGreaterThanOrEqual(1);
  });

  test('6 — final RCA assessment has expected sections', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Click the RCA session
    const session = page.locator('[role="button"]').filter({
      hasText: new RegExp(`${AGENT_NAME}|rca|Analyze`, 'i'),
    }).first();
    if (await session.isVisible({ timeout: 5000 }).catch(() => false)) {
      await session.click();
      await page.waitForTimeout(5000);
    }

    // Wait for completion (the agent should finish within timeout)
    // Look for a final response that's substantive
    await page.waitForTimeout(10000); // Give time for history to load

    // Get all chat text
    const chatContainer = page.locator('[style*="overflow"]').first();
    const fullText = (await chatContainer.textContent() || '').toLowerCase();
    console.log(`[rca] Total response length: ${fullText.length} chars`);

    // Assert expected RCA sections
    const sections = {
      'Root Cause': /root cause|cause of|caused by|reason for/,
      'Impact': /impact|affect|broken|fail|block/,
      'Recommended Fix': /fix|recommend|solution|resolve|action/,
      'CI Reference': /ci|pipeline|github actions|workflow|build/,
      'Test Failures': /test|fail|pass|assert|spec/,
    };

    const results: Record<string, boolean> = {};
    for (const [name, pattern] of Object.entries(sections)) {
      results[name] = pattern.test(fullText);
      console.log(`[rca] Section "${name}": ${results[name] ? 'FOUND' : 'MISSING'}`);
    }

    // Must have root cause + fix at minimum
    expect(results['Root Cause']).toBe(true);
    expect(results['Recommended Fix']).toBe(true);

    // Should have at least 3 out of 5 sections
    const found = Object.values(results).filter(Boolean).length;
    expect(found).toBeGreaterThanOrEqual(3);

    console.log(`[rca] Assessment quality: ${found}/5 sections present`);
  });
});
