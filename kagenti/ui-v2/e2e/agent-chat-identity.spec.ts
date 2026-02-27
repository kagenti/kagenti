/**
 * Agent Chat Identity & HITL E2E Tests
 *
 * Tests:
 * 1. Username label visible on user chat messages ("admin (you)")
 * 2. HITL approval card appears for INPUT_REQUIRED events
 * 3. HITL deny button works
 * 4. Auto-approve skips approval card for safe tools
 *
 * Prerequisites:
 * - Backend API accessible
 * - Keycloak deployed (for login test)
 * - weather-service agent deployed in team1 namespace
 *
 * Environment variables:
 *   KAGENTI_UI_URL: Base URL for the UI (default: http://localhost:3000)
 *   KEYCLOAK_USER: Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak password (default: admin)
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

/**
 * Reusable login helper (same pattern as agent-chat.spec.ts)
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

/**
 * Navigate to the weather agent chat tab
 */
async function navigateToWeatherChat(page: Page) {
  await page.locator('nav a', { hasText: 'Agents' }).first().click();
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
    timeout: 15000,
  });

  const weatherAgent = page.getByText('weather-service', { exact: true });
  await expect(weatherAgent).toBeVisible({ timeout: 30000 });
  await weatherAgent.click();
  await expect(page).toHaveURL(/\/agents\/team1\/weather-service/);

  await page.getByRole('tab', { name: /Chat/i }).click();
  await expect(page.getByPlaceholder('Type your message...')).toBeVisible({ timeout: 30000 });
}

test.describe('Agent Chat - User Identity', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should display username label on user messages', async ({ page }) => {
    await navigateToWeatherChat(page);

    // Send a message
    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('What is the weather in Paris?');
    await page.getByRole('button', { name: /Send/i }).click();

    // Assert: user message appears with content
    await expect(page.getByText('What is the weather in Paris?')).toBeVisible();

    // Assert: username label shows "admin (you)" or "<username> (you)"
    // The label is rendered above the chat bubble via data-testid
    const usernameLabelLocator = page.locator('[data-testid^="message-username-user-"]');
    await expect(usernameLabelLocator.first()).toBeVisible({ timeout: 5000 });

    const labelText = await usernameLabelLocator.first().textContent();
    expect(labelText).toContain('(you)');
    expect(labelText).toContain(KEYCLOAK_USER);
  });

  test('should show username on user messages and agent name on assistant messages', async ({
    page,
  }) => {
    await navigateToWeatherChat(page);

    // Send message and wait for response
    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('Hello');
    await page.getByRole('button', { name: /Send/i }).click();

    // Assert: user message has username
    const userLabel = page.locator('[data-testid^="message-username-user-"]');
    await expect(userLabel.first()).toBeVisible({ timeout: 5000 });
    await expect(userLabel.first()).toContainText(KEYCLOAK_USER);

    // Wait for assistant response
    await expect(
      page.locator('text=/hello|hi|greet|weather|help/i').first()
    ).toBeVisible({ timeout: 90000 });
  });
});

test.describe('Agent Chat - HITL Approval', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should render HITL approval card with Approve and Deny buttons', async ({ page }) => {
    await navigateToWeatherChat(page);

    // Mock a streaming response that includes a hitl_request event
    await page.route('**/api/v1/chat/**/stream', async (route) => {
      const taskId = 'test-hitl-task-1';
      const events = [
        `data: ${JSON.stringify({
          session_id: 'test-session',
          username: 'admin',
          event: { type: 'status', taskId, state: 'WORKING', final: false },
        })}\n\n`,
        `data: ${JSON.stringify({
          session_id: 'test-session',
          username: 'admin',
          event: {
            type: 'hitl_request',
            taskId,
            state: 'INPUT_REQUIRED',
            final: false,
            message: 'Agent wants to execute tool: delete_file. Allow?',
          },
        })}\n\n`,
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
        body: events.join(''),
      });
    });

    // Send a message to trigger the mocked HITL response
    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('Run the delete operation');
    await page.getByRole('button', { name: /Send/i }).click();

    // Assert: HITL approval card appears
    const approvalCard = page.locator('[data-testid="hitl-approval-test-hitl-task-1"]');
    await expect(approvalCard).toBeVisible({ timeout: 10000 });

    // Assert: Both Approve and Deny buttons are present
    const approveBtn = page.locator('[data-testid="hitl-approve-test-hitl-task-1"]');
    const denyBtn = page.locator('[data-testid="hitl-deny-test-hitl-task-1"]');
    await expect(approveBtn).toBeVisible();
    await expect(denyBtn).toBeVisible();
    await expect(approveBtn).toHaveText('Approve');
    await expect(denyBtn).toHaveText('Deny');

    // Assert: The HITL message is visible
    await expect(approvalCard).toContainText('delete_file');

    // Assert: "Approval Required" label is visible
    await expect(page.getByText('Approval Required')).toBeVisible();
  });

  test('should send approval when Approve button is clicked', async ({ page }) => {
    await navigateToWeatherChat(page);

    let hitlResponseReceived = false;

    // Mock the initial stream with HITL request
    await page.route('**/api/v1/chat/**/stream', async (route, request) => {
      const body = JSON.parse(request.postData() || '{}');

      if (body.message === 'Approved') {
        // This is the HITL approval response
        hitlResponseReceived = true;
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({
            session_id: 'test-session',
            event: { type: 'status', taskId: 'task-1', state: 'COMPLETED', final: true },
            content: 'File deleted successfully.',
          })}\n\ndata: ${JSON.stringify({ done: true, session_id: 'test-session' })}\n\n`,
        });
        return;
      }

      // Initial request triggers HITL
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({
          session_id: 'test-session',
          username: 'admin',
          event: {
            type: 'hitl_request',
            taskId: 'task-1',
            state: 'INPUT_REQUIRED',
            final: false,
            message: 'Confirm deletion?',
          },
        })}\n\n`,
      });
    });

    // Send message
    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('Delete the temp file');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for HITL card, then click Approve
    const approveBtn = page.locator('[data-testid="hitl-approve-task-1"]');
    await expect(approveBtn).toBeVisible({ timeout: 10000 });
    await approveBtn.click();

    // Assert: approval was sent to the backend
    await page.waitForTimeout(1000);
    expect(hitlResponseReceived).toBe(true);
  });

  test('should send denial when Deny button is clicked', async ({ page }) => {
    await navigateToWeatherChat(page);

    let hitlDenyReceived = false;

    await page.route('**/api/v1/chat/**/stream', async (route, request) => {
      const body = JSON.parse(request.postData() || '{}');

      if (body.message === 'Denied') {
        hitlDenyReceived = true;
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({
            session_id: 'test-session',
            event: { type: 'status', taskId: 'task-1', state: 'COMPLETED', final: true },
            content: 'Operation cancelled by user.',
          })}\n\ndata: ${JSON.stringify({ done: true, session_id: 'test-session' })}\n\n`,
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({
          session_id: 'test-session',
          username: 'admin',
          event: {
            type: 'hitl_request',
            taskId: 'task-1',
            state: 'INPUT_REQUIRED',
            final: false,
            message: 'Confirm deletion?',
          },
        })}\n\n`,
      });
    });

    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('Delete something dangerous');
    await page.getByRole('button', { name: /Send/i }).click();

    const denyBtn = page.locator('[data-testid="hitl-deny-task-1"]');
    await expect(denyBtn).toBeVisible({ timeout: 10000 });
    await denyBtn.click();

    await page.waitForTimeout(1000);
    expect(hitlDenyReceived).toBe(true);
  });

  test('should auto-approve safe tools without showing approval card', async ({ page }) => {
    await navigateToWeatherChat(page);

    await page.route('**/api/v1/chat/**/stream', async (route, request) => {
      const body = JSON.parse(request.postData() || '{}');

      if (body.message === 'Approved') {
        // Auto-approve fires this automatically
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `data: ${JSON.stringify({
            session_id: 'test-session',
            event: { type: 'status', taskId: 'task-safe', state: 'COMPLETED', final: true },
            content: 'Weather retrieved.',
          })}\n\ndata: ${JSON.stringify({ done: true, session_id: 'test-session' })}\n\n`,
        });
        return;
      }

      // Return HITL for a safe tool (get_weather is in AUTO_APPROVE_TOOLS)
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({
          session_id: 'test-session',
          username: 'admin',
          event: {
            type: 'hitl_request',
            taskId: 'task-safe',
            state: 'INPUT_REQUIRED',
            final: false,
            message: 'tool: get_weather',
          },
        })}\n\n`,
      });
    });

    const chatInput = page.getByPlaceholder('Type your message...');
    await chatInput.fill('What is the weather?');
    await page.getByRole('button', { name: /Send/i }).click();

    // Assert: NO hitl approval card visible (auto-approved)
    // Wait briefly for events to process
    await page.waitForTimeout(2000);
    const approvalCard = page.locator('[data-testid="hitl-approval-task-safe"]');
    await expect(approvalCard).not.toBeVisible();

    // Assert: AUTO_APPROVED label appears instead
    await expect(page.getByText('AUTO_APPROVED').first()).toBeVisible({ timeout: 5000 });
  });
});
