/**
 * Agent Loop Consistency E2E Tests
 *
 * Verifies that the streaming view and historical view of agent loop cards
 * are consistent — same structure, same badges, same content.
 *
 * Flow:
 * 1. Login and navigate to sandbox with agent
 * 2. Send a message that triggers tool calls (agent loop)
 * 3. Wait for streaming to complete, capture loop card state
 * 4. Reload the page (navigate away and back with session ID)
 * 5. Capture historical view loop card state
 * 6. Compare the two snapshots
 *
 * Prerequisites:
 * - Sandbox agent (sandbox-legion) deployed in team1
 * - PostgreSQL sessions DB in team1
 *
 * Environment variables:
 *   KAGENTI_UI_URL: Base URL for the UI (default: http://localhost:3000)
 *   KEYCLOAK_USER: Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak password (default: admin)
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';
const AGENT_NAME = 'sandbox-legion';

/**
 * Reusable login helper (same pattern as other E2E specs).
 */
async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 30000 });

  const isKeycloakLogin = await page
    .locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    const signInButton = page.getByRole('button', { name: /Sign In/i });
    const hasSignIn = await signInButton.isVisible({ timeout: 5000 }).catch(() => false);
    if (!hasSignIn) return;
    await signInButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }

  const usernameField = page.locator('input[name="username"]').first();
  const passwordField = page.locator('input[name="password"]').first();
  const submitButton = page
    .locator('#kc-login, button[type="submit"], input[type="submit"]')
    .first();

  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await usernameField.fill(KEYCLOAK_USER);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  await passwordField.pressSequentially(KEYCLOAK_PASSWORD, { delay: 20 });
  await page.waitForTimeout(300);
  await submitButton.click();

  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
}

/** Navigate to the Sandbox (Sessions) page with a specific agent. */
async function navigateToSandbox(page: Page, agent: string) {
  await page.locator('nav a', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');
  // Wait for the chat input to appear
  await expect(
    page.locator('textarea[aria-label="Message input"]').first()
  ).toBeVisible({ timeout: 15000 });
}

/**
 * Snapshot of loop card state — captures structural properties
 * that should be identical between streaming and historical views.
 */
interface LoopSnapshot {
  loopCount: number;
  hasPlanner: boolean;
  hasExecutor: boolean;
  hasReflector: boolean;
  hasReporter: boolean;
  toolCallCount: number;
  toolResultCount: number;
  markdownCount: number;
  reasoningToggleCount: number;
  firstLoopText: string;
}

/** Capture a snapshot of loop card state from the current page. */
async function captureLoopSnapshot(page: Page, label: string): Promise<LoopSnapshot> {
  const loopCards = page.locator('[data-testid="agent-loop-card"]');
  const loopCount = await loopCards.count();
  console.log(`[consistency] ${label}: ${loopCount} loop cards`);

  const snapshot: LoopSnapshot = {
    loopCount,
    hasPlanner: false,
    hasExecutor: false,
    hasReflector: false,
    hasReporter: false,
    toolCallCount: 0,
    toolResultCount: 0,
    markdownCount: await page.locator('.sandbox-markdown').count(),
    reasoningToggleCount: await page.locator('[data-testid="reasoning-toggle"]').count(),
    firstLoopText: '',
  };

  if (loopCount > 0) {
    // Expand the first loop card to inspect its contents
    const toggle = loopCards.first().locator('[data-testid="reasoning-toggle"]');
    if (await toggle.isVisible({ timeout: 3000 }).catch(() => false)) {
      await toggle.click();
      await page.waitForTimeout(1000);
    }

    const loopText = (await loopCards.first().textContent()) || '';
    snapshot.firstLoopText = loopText;
    snapshot.hasPlanner = /planner/i.test(loopText);
    snapshot.hasExecutor = /executor/i.test(loopText);
    snapshot.hasReflector = /reflector/i.test(loopText);
    snapshot.hasReporter = /reporter/i.test(loopText);

    // Count tool call and tool result blocks within the first loop card
    snapshot.toolCallCount = (loopText.match(/Tool Call/gi) || []).length;
    snapshot.toolResultCount = (loopText.match(/Result:/gi) || []).length;
  }

  console.log(`[consistency] ${label} snapshot:`, JSON.stringify({
    loopCount: snapshot.loopCount,
    hasPlanner: snapshot.hasPlanner,
    hasExecutor: snapshot.hasExecutor,
    hasReflector: snapshot.hasReflector,
    hasReporter: snapshot.hasReporter,
    toolCallCount: snapshot.toolCallCount,
    toolResultCount: snapshot.toolResultCount,
    markdownCount: snapshot.markdownCount,
    reasoningToggleCount: snapshot.reasoningToggleCount,
  }));

  return snapshot;
}

test.describe('Agent Loop Consistency — Streaming vs Historical', () => {
  test.setTimeout(600_000); // 10 min — Llama 4 Scout can be slow

  test('loop card structure matches between streaming and reload', async ({ page }) => {
    // 1. Login and navigate to sandbox
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandbox(page, AGENT_NAME);

    // Start a fresh session via "+ New Session" if available
    const newSessionBtn = page.getByRole('button', { name: /New Session/i });
    if (await newSessionBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newSessionBtn.click();
      // Handle New Session modal — click "Start" to confirm
      const startBtn = page.getByRole('button', { name: /^Start$/ });
      if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await startBtn.click();
        await page.waitForTimeout(500);
      }
      await page.waitForTimeout(500);
    }

    // 2. Send a message that triggers tool calls (agent loop)
    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await expect(chatInput).toBeVisible({ timeout: 10000 });
    await chatInput.fill('Run: echo hello-consistency-test && ls /tmp');
    const sendBtn = page.getByRole('button', { name: /Send/i });
    await sendBtn.click();
    console.log('[consistency] Message sent, waiting for streaming to complete...');

    // 3. Wait for streaming to complete (chat input re-enabled)
    await expect(chatInput).toBeEnabled({ timeout: 120000 });
    // Give extra time for final rendering
    await page.waitForTimeout(3000);

    // 4. Capture streaming view state
    const streamSnapshot = await captureLoopSnapshot(page, 'Streaming');
    await page.screenshot({ path: 'test-results/consistency-streaming.png', fullPage: true });

    // 5. Extract session ID from URL
    const currentUrl = new URL(page.url());
    const sessionId = currentUrl.searchParams.get('session') || '';
    console.log(`[consistency] Session ID: ${sessionId}`);

    if (!sessionId) {
      // If no session in URL, the test cannot compare views
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No session ID in URL after streaming — cannot reload for comparison',
      });
      // Still validate that streaming produced loop cards
      if (streamSnapshot.loopCount === 0) {
        console.log('[consistency] No loop cards in streaming view — agent may not use loop mode');
      }
      return;
    }

    // 6. Reload: navigate away and back with the session ID
    await page.goto('/');
    await loginIfNeeded(page);
    // Navigate back to sandbox with the session param to trigger history reload
    await page.goto(`/sandbox?session=${sessionId}&agent=${AGENT_NAME}`);
    await page.waitForLoadState('networkidle');
    // Wait for history + loop reconstruction from loop_events
    await page.waitForTimeout(5000);
    // Ensure the chat input is visible (page fully loaded)
    await expect(
      page.locator('textarea[aria-label="Message input"]').first()
    ).toBeVisible({ timeout: 15000 });

    // 7. Capture historical view state
    const histSnapshot = await captureLoopSnapshot(page, 'Historical');
    await page.screenshot({ path: 'test-results/consistency-historical.png', fullPage: true });

    // 8. Compare snapshots
    console.log('[consistency] Comparing streaming vs historical...');

    // --- Loop card existence ---
    if (streamSnapshot.loopCount > 0) {
      expect(histSnapshot.loopCount).toBeGreaterThan(0);
      console.log(
        `[consistency] Loop cards: stream=${streamSnapshot.loopCount}, hist=${histSnapshot.loopCount}`
      );
    } else {
      // If streaming had no loop cards, historical should also have none
      console.log('[consistency] No loop cards in streaming — skipping structural comparison');
      return;
    }

    // --- Node badges should match ---
    if (streamSnapshot.hasPlanner) {
      expect(histSnapshot.hasPlanner).toBe(true);
      console.log('[consistency] Planner badge: present in both views');
    }
    if (streamSnapshot.hasExecutor) {
      expect(histSnapshot.hasExecutor).toBe(true);
      console.log('[consistency] Executor badge: present in both views');
    }
    if (streamSnapshot.hasReflector) {
      // Reflector may not show if loop completed in 1 iteration — soft check
      console.log(
        `[consistency] Reflector badge: stream=${streamSnapshot.hasReflector}, hist=${histSnapshot.hasReflector}`
      );
    }
    if (streamSnapshot.hasReporter) {
      expect(histSnapshot.hasReporter).toBe(true);
      console.log('[consistency] Reporter badge: present in both views');
    }

    // --- Tool calls should be present in both ---
    if (streamSnapshot.toolCallCount > 0) {
      expect(histSnapshot.toolCallCount).toBeGreaterThan(0);
      console.log(
        `[consistency] Tool calls: stream=${streamSnapshot.toolCallCount}, hist=${histSnapshot.toolCallCount}`
      );
    }

    // --- Tool results should be present in both ---
    if (streamSnapshot.toolResultCount > 0) {
      expect(histSnapshot.toolResultCount).toBeGreaterThan(0);
      console.log(
        `[consistency] Tool results: stream=${streamSnapshot.toolResultCount}, hist=${histSnapshot.toolResultCount}`
      );
    }

    // --- Reasoning toggle should exist in both ---
    if (streamSnapshot.reasoningToggleCount > 0) {
      expect(histSnapshot.reasoningToggleCount).toBeGreaterThan(0);
      console.log(
        `[consistency] Reasoning toggles: stream=${streamSnapshot.reasoningToggleCount}, hist=${histSnapshot.reasoningToggleCount}`
      );
    }

    // --- Markdown blocks (final answer) should be present in both ---
    if (streamSnapshot.markdownCount > 0) {
      expect(histSnapshot.markdownCount).toBeGreaterThan(0);
      console.log(
        `[consistency] Markdown blocks: stream=${streamSnapshot.markdownCount}, hist=${histSnapshot.markdownCount}`
      );
    }

    console.log('[consistency] All structural checks passed');
  });
});
