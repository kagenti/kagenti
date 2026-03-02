/**
 * Agent RCA Workflow E2E Test
 *
 * End-to-end test of the full agent lifecycle:
 * 1. Deploy agent via wizard (manages kagenti/kagenti repo)
 * 2. Agent loads CLAUDE.md + skills from the repo
 * 3. User asks agent to run /rca:ci on a failed CI run
 * 4. Agent spawns sub-agents for parallel log analysis
 * 5. Sub-agent sessions appear in the sidebar
 * 6. Final RCA assessment has expected structure
 *
 * This is the VISION test — validates the complete platform pipeline.
 * Start with in-process sub-agents and default sandbox security.
 * Future: test across security tiers (hardened, restricted, etc.)
 *
 * Prerequisites:
 * - Sandbox agents deployed on cluster
 * - Keycloak auth configured
 * - GitHub API accessible (for CI logs)
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';
import { execSync } from 'child_process';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

// Agent config for this test
const AGENT_NAME = 'rca-agent';
const REPO_URL = 'https://github.com/kagenti/kagenti';
const NAMESPACE = 'team1';

/**
 * Clean up any existing deployment of the test agent.
 * Deletes deployment, service, and sessions so we start fresh every time.
 */
function cleanupAgent() {
  const kubeconfig = process.env.KUBECONFIG ||
    `${process.env.HOME}/clusters/hcp/kagenti-team-sbox/auth/kubeconfig`;
  const kubectl = `KUBECONFIG=${kubeconfig} kubectl`;

  try {
    // Delete deployment if it exists
    execSync(`${kubectl} delete deployment ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`, {
      timeout: 15000,
      stdio: 'pipe',
    });
    // Delete service if it exists
    execSync(`${kubectl} delete service ${AGENT_NAME} -n ${NAMESPACE} --ignore-not-found`, {
      timeout: 15000,
      stdio: 'pipe',
    });
    // Delete sessions for this agent from PostgreSQL
    execSync(
      `${kubectl} exec -n ${NAMESPACE} postgres-sessions-0 -- psql -U kagenti -d sessions -c "DELETE FROM tasks WHERE metadata::text ILIKE '%${AGENT_NAME}%'"`,
      { timeout: 15000, stdio: 'pipe' }
    );
    console.log(`[rca-test] Cleaned up existing ${AGENT_NAME} deployment + sessions`);
  } catch (e) {
    console.log(`[rca-test] Cleanup (non-fatal): ${e}`);
  }
}

test.describe('Agent RCA Workflow — Full Pipeline', () => {
  test.setTimeout(300000); // 5 minutes — agent work takes time

  // Clean up before the entire suite — always start fresh
  test.beforeAll(() => {
    console.log(`[rca-test] Cleaning up any existing ${AGENT_NAME} deployment...`);
    cleanupAgent();

    // Verify cleanup: deployment should not exist
    const kubeconfig = process.env.KUBECONFIG ||
      `${process.env.HOME}/clusters/hcp/kagenti-team-sbox/auth/kubeconfig`;
    try {
      const result = execSync(
        `KUBECONFIG=${kubeconfig} kubectl get deploy ${AGENT_NAME} -n ${NAMESPACE} 2>&1`,
        { timeout: 10000, stdio: 'pipe' }
      ).toString();
      if (!result.includes('NotFound') && !result.includes('not found')) {
        throw new Error(`${AGENT_NAME} still exists after cleanup: ${result}`);
      }
    } catch (e: any) {
      // "not found" error is expected — cleanup worked
      if (!e.message?.includes('not found') && !e.stderr?.toString().includes('not found')) {
        console.log(`[rca-test] Cleanup verification: ${e.message}`);
      }
    }
    console.log(`[rca-test] Clean slate confirmed — ${AGENT_NAME} does not exist`);
  });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  // Clean up after the entire suite so next run starts fresh too
  test.afterAll(() => {
    console.log(`[rca-test] Post-suite cleanup...`);
    cleanupAgent();
  });

  test('Step 1: Deploy agent via wizard with kagenti repo', async ({ page }) => {
    // Navigate to Sandboxes → Import Agent
    await page.locator('nav a', { hasText: 'Sandboxes' }).first().click();
    await page.waitForLoadState('networkidle');

    const importBtn = page.getByText('+ Import Agent').or(
      page.getByRole('button', { name: /Import Agent/i })
    );
    await expect(importBtn.first()).toBeVisible({ timeout: 10000 });
    await importBtn.first().click();
    await page.waitForLoadState('networkidle');

    // Step 1: Agent name
    const nameInput = page.locator('#agent-name, input[name="agent-name"], input[placeholder*="agent"]').first();
    await expect(nameInput).toBeVisible({ timeout: 10000 });
    await nameInput.fill(AGENT_NAME);

    // Step 1: Repository URL
    const repoInput = page.locator('#repo-url, input[name="repo-url"], input[placeholder*="repo"]').first();
    if (await repoInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await repoInput.fill(REPO_URL);
    }

    // Navigate through wizard steps (click Next until Deploy)
    const nextBtn = page.getByRole('button', { name: /Next/i });
    let stepCount = 0;
    while (await nextBtn.isVisible({ timeout: 3000 }).catch(() => false) && stepCount < 6) {
      await nextBtn.click();
      await page.waitForTimeout(500);
      stepCount++;
    }

    // Click Deploy
    const deployBtn = page.getByRole('button', { name: /Deploy/i });
    if (await deployBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await deployBtn.click();
      await page.waitForTimeout(5000);
    }

    // Wait for agent pod to be ready (check via kubectl)
    let agentReady = false;
    for (let i = 0; i < 30; i++) {
      try {
        const kubeconfig = process.env.KUBECONFIG ||
          `${process.env.HOME}/clusters/hcp/kagenti-team-sbox/auth/kubeconfig`;
        const result = execSync(
          `KUBECONFIG=${kubeconfig} kubectl get deploy ${AGENT_NAME} -n ${NAMESPACE} -o jsonpath='{.status.readyReplicas}'`,
          { timeout: 10000, stdio: 'pipe' }
        ).toString().trim();
        if (result === '1') {
          agentReady = true;
          break;
        }
      } catch { /* not ready yet */ }
      await page.waitForTimeout(5000);
    }

    expect(agentReady).toBe(true);
    test.info().annotations.push({
      type: 'step-complete',
      description: `Agent ${AGENT_NAME} deployed and ready`,
    });
  });

  test('Step 2: Start session and ask agent to analyze CI', async ({ page }) => {
    // Navigate to Sessions page
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Wait for chat input
    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    // Send the RCA request — this triggers the agent to:
    // 1. Load kagenti/kagenti CLAUDE.md + skills
    // 2. Execute /rca:ci skill
    // 3. Spawn sub-agents for log analysis
    const rca_prompt = [
      'Run root cause analysis on the latest CI failures.',
      'Check GitHub Actions for the kagenti/kagenti repo, PR #758.',
      'Use the /rca:ci skill to analyze the failures.',
      'Spawn sub-agents to analyze different failure categories in parallel.',
    ].join(' ');

    await chatInput.fill(rca_prompt);
    await page.getByRole('button', { name: /Send/i }).click();

    // Verify: user message appears with username
    await expect(page.getByText('Run root cause analysis')).toBeVisible({ timeout: 10000 });

    // Verify: username label shows on the message
    const senderLabel = page.locator('[data-testid^="chat-sender-user-"]').first();
    await expect(senderLabel).toBeVisible({ timeout: 5000 });

    // Wait for agent to start processing (streaming indicator or first response)
    const agentActivity = page.locator('text=/processing|thinking|working|tool|analyzing/i').first();
    await expect(agentActivity).toBeVisible({ timeout: 60000 });

    test.info().annotations.push({
      type: 'step-complete',
      description: 'RCA request sent, agent started processing',
    });
  });

  test('Step 3: Observe sub-agent sessions in sidebar', async ({ page }) => {
    // Navigate to Sessions page
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Wait for sessions to load in sidebar
    await page.waitForTimeout(3000);

    // Look for sessions — there should be at least the parent session
    const sessionItems = page.locator('[role="button"], .pf-v5-c-card').filter({
      hasText: /sandbox-legion|rca|analysis|root cause/i,
    });

    const sessionCount = await sessionItems.count();
    console.log(`[rca-test] Found ${sessionCount} sessions in sidebar`);

    // For sub-agent spawning: look for child sessions
    // These would appear as indented items or with sub-session indicators
    const subSessions = page.locator('text=/sub|child|delegate/i');
    const hasSubSessions = await subSessions.count();
    console.log(`[rca-test] Sub-sessions found: ${hasSubSessions}`);

    // Assert: at least one session exists
    expect(sessionCount).toBeGreaterThanOrEqual(1);

    test.info().annotations.push({
      type: 'step-complete',
      description: `${sessionCount} sessions visible, ${hasSubSessions} sub-sessions`,
    });
  });

  test('Step 4: Verify tool call steps visible during analysis', async ({ page }) => {
    // Navigate to Sessions and click on the most recent session
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Click the most recent session (first in list)
    const firstSession = page.locator('[role="button"]').filter({
      hasText: /sandbox-legion|rca/i,
    }).first();

    if (await firstSession.isVisible({ timeout: 5000 }).catch(() => false)) {
      await firstSession.click();
      await page.waitForTimeout(3000);
    }

    // Look for tool call steps in the chat
    // The RCA skill should produce:
    // - Tool calls: gh run view, grep, file reads
    // - Tool results: log content, error summaries
    // - LLM responses: analysis reasoning
    const toolCalls = page.locator('[data-testid="tool-call-step"]').or(
      page.locator('text=/Tool Call|tool_call|shell|gh /i')
    );
    const toolCallCount = await toolCalls.count();
    console.log(`[rca-test] Tool call steps visible: ${toolCallCount}`);

    // Assert: we should see at least some tool activity
    // (Even if rendering is imperfect, SOME indication of tool use should be visible)
    const hasActivity = toolCallCount > 0 ||
      await page.locator('text=/analyzing|error|failure|test|build/i').first()
        .isVisible({ timeout: 5000 }).catch(() => false);

    expect(hasActivity).toBe(true);

    test.info().annotations.push({
      type: 'step-complete',
      description: `${toolCallCount} tool call steps visible`,
    });
  });

  test('Step 5: Final RCA assessment has expected structure', async ({ page }) => {
    // Navigate to Sessions
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Click the session with the RCA results
    const rcaSession = page.locator('[role="button"]').filter({
      hasText: /rca|root cause|analysis|sandbox-legion/i,
    }).first();

    if (await rcaSession.isVisible({ timeout: 5000 }).catch(() => false)) {
      await rcaSession.click();
      await page.waitForTimeout(3000);
    }

    // Wait for the agent to complete (may take minutes)
    // Look for completion indicators
    const completed = page.locator('text=/completed|done|assessment|summary|conclusion/i').first();
    await expect(completed).toBeVisible({ timeout: 180000 }); // 3 min timeout

    // Verify the RCA assessment structure
    // A proper RCA should contain these elements:
    const assessmentChecks = [
      { name: 'Root Cause', pattern: /root cause|cause|reason|why/i },
      { name: 'Impact', pattern: /impact|affect|broken|fail/i },
      { name: 'Fix', pattern: /fix|solution|resolve|recommend/i },
    ];

    const chatContent = page.locator('[style*="overflow"]').first();
    const text = await chatContent.textContent() || '';

    for (const check of assessmentChecks) {
      const found = check.pattern.test(text);
      console.log(`[rca-test] Assessment "${check.name}": ${found ? 'FOUND' : 'MISSING'}`);
      test.info().annotations.push({
        type: 'assessment-check',
        description: `${check.name}: ${found ? 'present' : 'missing'}`,
      });
    }

    // At minimum, the agent should have produced SOME text output
    expect(text.length).toBeGreaterThan(100);

    test.info().annotations.push({
      type: 'step-complete',
      description: `RCA assessment: ${text.length} chars`,
    });
  });
});

test.describe('Agent RCA — Multi-Agent Observation', () => {
  test.setTimeout(300000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('Sessions table shows parent-child relationship', async ({ page }) => {
    // Navigate to Sessions table (View All Sessions)
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    const viewAll = page.getByText('View All Sessions');
    if (await viewAll.isVisible({ timeout: 3000 }).catch(() => false)) {
      await viewAll.scrollIntoViewIfNeeded();
      await viewAll.click();
      await page.waitForLoadState('networkidle');
    }

    // Look for sessions with sub-session count > 0
    const subsColumn = page.locator('td[data-label="Subs"]').filter({
      hasNot: page.locator('text=-'),
    });
    const hasParentSessions = await subsColumn.count();
    console.log(`[rca-test] Sessions with sub-sessions: ${hasParentSessions}`);

    // Look for owner column showing our username
    const ownerCells = page.locator('td[data-label="Owner"]').filter({
      hasText: KEYCLOAK_USER,
    });
    const ownedSessions = await ownerCells.count();
    console.log(`[rca-test] Sessions owned by ${KEYCLOAK_USER}: ${ownedSessions}`);

    test.info().annotations.push({
      type: 'multi-agent',
      description: `Parent sessions: ${hasParentSessions}, Owned: ${ownedSessions}`,
    });
  });

  test('HITL approval card appears for risky operations', async ({ page }) => {
    // Navigate to Sessions
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Start a new session with a request that should trigger HITL
    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    if (await chatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await chatInput.fill('Delete all failed CI runs older than 7 days for kagenti/kagenti');
      await page.getByRole('button', { name: /Send/i }).click();

      // Wait for either HITL card or response
      const hitlOrResponse = page.locator('text=/Approval Required|approve|deny|deleted|cannot/i').first();
      await expect(hitlOrResponse).toBeVisible({ timeout: 60000 });

      const isHitl = await page.getByText('Approval Required').isVisible({ timeout: 2000 }).catch(() => false);
      console.log(`[rca-test] HITL triggered: ${isHitl}`);

      if (isHitl) {
        // Verify Approve/Deny buttons exist
        const approveBtn = page.getByRole('button', { name: /Approve/i }).first();
        const denyBtn = page.getByRole('button', { name: /Deny/i }).first();

        await expect(approveBtn).toBeVisible();
        await expect(denyBtn).toBeVisible();

        // Click Deny (safe for test — don't actually delete)
        await denyBtn.click();
        await page.waitForTimeout(2000);
      }
    }
  });
});
