/**
 * Sandbox Delegation E2E Tests (Session E)
 *
 * Tests delegation events rendering in the SandboxPage chat:
 * 1. Delegation event card appears when legion spawns a child session
 * 2. Delegation mode badge (in-process, isolated, shared-pvc) is visible
 * 3. Child session status updates render in real-time
 * 4. Link to child session navigates correctly
 * 5. Multiple concurrent delegations display correctly
 *
 * All tests use mocked SSE streams — no live agent required.
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

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

/** Navigate to the Sessions chat page */
async function navigateToSandboxChat(page: Page) {
  await page.locator('nav a', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');
  await expect(
    page.locator('textarea[placeholder*="message"], textarea[aria-label="Message input"]').first()
  ).toBeVisible({ timeout: 15000 });
}

// ─── SSE Event Builders ─────────────────────────────────────────────────────

function sseEvent(data: Record<string, unknown>): string {
  return `data: ${JSON.stringify(data)}\n\n`;
}

function delegationStartEvent(opts: {
  sessionId: string;
  childId: string;
  mode: string;
  task: string;
  variant: string;
}): string {
  return sseEvent({
    session_id: opts.sessionId,
    event: {
      type: 'delegation_start',
      child_context_id: opts.childId,
      delegation_mode: opts.mode,
      task: opts.task,
      variant: opts.variant,
      state: 'WORKING',
      final: false,
    },
    content: `Delegating: ${opts.task} (${opts.mode})`,
  });
}

function delegationProgressEvent(opts: {
  sessionId: string;
  childId: string;
  status: string;
  message: string;
}): string {
  return sseEvent({
    session_id: opts.sessionId,
    event: {
      type: 'delegation_progress',
      child_context_id: opts.childId,
      status: opts.status,
      final: false,
    },
    content: opts.message,
  });
}

function delegationCompleteEvent(opts: {
  sessionId: string;
  childId: string;
  result: string;
}): string {
  return sseEvent({
    session_id: opts.sessionId,
    event: {
      type: 'delegation_complete',
      child_context_id: opts.childId,
      state: 'COMPLETED',
      final: false,
    },
    content: opts.result,
  });
}

function doneEvent(sessionId: string): string {
  return sseEvent({ done: true, session_id: sessionId });
}

// ─── Tests ───────────────────────────────────────────────────────────────────

test.describe('Sandbox Delegation - Event Cards', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should show delegation card when legion spawns in-process child', async ({ page }) => {
    await navigateToSandboxChat(page);

    // Mock SSE to return delegation events
    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-delegation-session';
      const body = [
        delegationStartEvent({
          sessionId,
          childId: 'child-inproc-001',
          mode: 'in-process',
          task: 'explore the auth module',
          variant: 'sandbox-legion',
        }),
        delegationCompleteEvent({
          sessionId,
          childId: 'child-inproc-001',
          result: 'Found 3 auth files: auth.py, middleware.py, keycloak.py',
        }),
        sseEvent({
          session_id: sessionId,
          content: 'I explored the auth module and found 3 key files.',
          event: { type: 'llm_response', state: 'COMPLETED', final: true },
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    // Send a message to trigger delegation
    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Explore the auth module');
    await page.getByRole('button', { name: /Send/i }).click();

    // Delegation card should appear
    const delegationCard = page.locator('[data-testid="delegation-card-child-inproc-001"]');
    await expect(delegationCard).toBeVisible({ timeout: 15000 });

    // Card should show the delegation mode
    await expect(delegationCard.locator('[data-testid="delegation-mode-badge"]')).toContainText('in-process');

    // Card should show the task description
    await expect(delegationCard).toContainText('explore the auth module');

    // Card should show completed result
    await expect(delegationCard).toContainText(/Found 3 auth files|auth\.py/);
  });

  test('should show delegation card with isolated mode for PR build', async ({ page }) => {
    await navigateToSandboxChat(page);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-isolated-session';
      const body = [
        delegationStartEvent({
          sessionId,
          childId: 'child-iso-002',
          mode: 'isolated',
          task: 'build feature-auth PR',
          variant: 'sandbox-legion-secctx',
        }),
        delegationProgressEvent({
          sessionId,
          childId: 'child-iso-002',
          status: 'working',
          message: 'Creating branch and workspace...',
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Build a PR for the auth feature');
    await page.getByRole('button', { name: /Send/i }).click();

    const delegationCard = page.locator('[data-testid="delegation-card-child-iso-002"]');
    await expect(delegationCard).toBeVisible({ timeout: 15000 });

    // Should show isolated mode badge
    await expect(delegationCard.locator('[data-testid="delegation-mode-badge"]')).toContainText('isolated');

    // Should show the variant used
    await expect(delegationCard).toContainText('sandbox-legion-secctx');

    // Should show the task
    await expect(delegationCard).toContainText('build feature-auth PR');
  });

  test('should show shared-pvc delegation with parent file access', async ({ page }) => {
    await navigateToSandboxChat(page);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-shared-session';
      const body = [
        delegationStartEvent({
          sessionId,
          childId: 'child-shared-003',
          mode: 'shared-pvc',
          task: 'run tests on current changes',
          variant: 'sandbox-legion',
        }),
        delegationCompleteEvent({
          sessionId,
          childId: 'child-shared-003',
          result: '42 tests passed, 0 failed',
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Run the tests on my changes');
    await page.getByRole('button', { name: /Send/i }).click();

    const delegationCard = page.locator('[data-testid="delegation-card-child-shared-003"]');
    await expect(delegationCard).toBeVisible({ timeout: 15000 });

    // Should show shared-pvc mode
    await expect(delegationCard.locator('[data-testid="delegation-mode-badge"]')).toContainText('shared-pvc');

    // Should show the result
    await expect(delegationCard).toContainText('42 tests passed');
  });
});

test.describe('Sandbox Delegation - Multiple Children', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should render multiple concurrent delegation cards', async ({ page }) => {
    await navigateToSandboxChat(page);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-multi-session';
      const body = [
        // Two children spawned in parallel
        delegationStartEvent({
          sessionId,
          childId: 'child-multi-a',
          mode: 'isolated',
          task: 'build feature-auth',
          variant: 'sandbox-legion',
        }),
        delegationStartEvent({
          sessionId,
          childId: 'child-multi-b',
          mode: 'isolated',
          task: 'build feature-rbac',
          variant: 'sandbox-legion',
        }),
        // First child completes
        delegationCompleteEvent({
          sessionId,
          childId: 'child-multi-a',
          result: 'PR #42 created for feature-auth',
        }),
        // Second child completes
        delegationCompleteEvent({
          sessionId,
          childId: 'child-multi-b',
          result: 'PR #43 created for feature-rbac',
        }),
        sseEvent({
          session_id: sessionId,
          content: 'Both features built. PR #42 (auth) and PR #43 (rbac) created.',
          event: { type: 'llm_response', state: 'COMPLETED', final: true },
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Build both auth and rbac features in parallel');
    await page.getByRole('button', { name: /Send/i }).click();

    // Both delegation cards should be visible
    await expect(
      page.locator('[data-testid="delegation-card-child-multi-a"]')
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.locator('[data-testid="delegation-card-child-multi-b"]')
    ).toBeVisible();

    // Both should show results
    await expect(
      page.locator('[data-testid="delegation-card-child-multi-a"]')
    ).toContainText('PR #42');
    await expect(
      page.locator('[data-testid="delegation-card-child-multi-b"]')
    ).toContainText('PR #43');
  });
});

test.describe('Sandbox Delegation - Child Session Link', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should have clickable link to view child session', async ({ page }) => {
    await navigateToSandboxChat(page);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-link-session';
      const body = [
        delegationStartEvent({
          sessionId,
          childId: 'child-link-001',
          mode: 'in-process',
          task: 'analyze codebase',
          variant: 'sandbox-legion',
        }),
        delegationCompleteEvent({
          sessionId,
          childId: 'child-link-001',
          result: 'Analysis complete',
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Analyze the codebase');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for delegation card
    const delegationCard = page.locator('[data-testid="delegation-card-child-link-001"]');
    await expect(delegationCard).toBeVisible({ timeout: 15000 });

    // Should have a "View Session" or "Open" link
    const viewLink = delegationCard.locator('[data-testid="delegation-view-child-link"]');
    await expect(viewLink).toBeVisible();

    // Click should navigate to the child session (or open graph)
    await viewLink.click();
    await expect(page).toHaveURL(
      /session=child-link-001|contextId=child-link-001|\/sandbox\/graph/,
      { timeout: 10000 }
    );
  });

  test('should show View Graph button linking to graph page', async ({ page }) => {
    await navigateToSandboxChat(page);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const sessionId = 'test-graph-link-session';
      const body = [
        delegationStartEvent({
          sessionId,
          childId: 'child-graph-001',
          mode: 'isolated',
          task: 'build feature',
          variant: 'sandbox-legion',
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page.locator('textarea[aria-label="Message input"]').first();
    await chatInput.fill('Build a feature');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for delegation card
    await expect(
      page.locator('[data-testid="delegation-card-child-graph-001"]')
    ).toBeVisible({ timeout: 15000 });

    // Should have a "View Graph" button/link
    const graphLink = page.locator('[data-testid="delegation-view-graph-link"]');
    await expect(graphLink).toBeVisible();

    await graphLink.click();
    await expect(page).toHaveURL(/\/sandbox\/graph/, { timeout: 10000 });
  });
});
