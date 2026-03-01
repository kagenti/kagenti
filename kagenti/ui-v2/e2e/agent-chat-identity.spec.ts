/**
 * Agent Chat Identity, HITL & Multi-User E2E Tests
 *
 * Tests:
 * 1. Username label visible on user chat messages ("admin (you)")
 * 2. HITL approval card appears for INPUT_REQUIRED events
 * 3. HITL deny button works
 * 4. Auto-approve skips approval card for safe tools
 * 5. Multi-user: admin and dev-user see correct identity labels
 * 6. Multi-user: dev-user cannot see admin's sessions (RBAC)
 *
 * Prerequisites:
 * - Backend API accessible
 * - Keycloak deployed with demo realm
 * - Test users created (admin, dev-user, ns-admin) via keycloak-realm-init
 * - weather-service agent deployed in team1 namespace
 *
 * Environment variables:
 *   KAGENTI_UI_URL: Base URL for the UI (default: http://localhost:3000)
 *   KEYCLOAK_USER: Keycloak admin username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak admin password (default: admin)
 */
import { test, expect, type Page, type BrowserContext } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

// Test users created by keycloak-realm-init Helm template
const DEV_USER = 'dev-user';
const DEV_PASSWORD = 'dev-user';
const NS_ADMIN_USER = 'ns-admin';
const NS_ADMIN_PASSWORD = 'ns-admin';

/**
 * Login to Keycloak with specific credentials.
 * Works with both community Keycloak and Red Hat Build of Keycloak.
 */
async function loginAs(page: Page, username: string, password: string) {
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
  await usernameField.fill(username);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  await passwordField.pressSequentially(password, { delay: 20 });
  await page.waitForTimeout(300);
  await submitButton.click();

  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
}

/**
 * Reusable login helper with default credentials
 */
async function loginIfNeeded(page: Page) {
  await loginAs(page, KEYCLOAK_USER, KEYCLOAK_PASSWORD);
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

    // Assert: Events panel exists (contains the auto-approved event)
    // The panel may be collapsed, so expand it to verify the AUTO_APPROVED label
    const eventsToggle = page.getByText(/Events \(\d+\)/).first();
    await expect(eventsToggle).toBeVisible({ timeout: 5000 });
    await eventsToggle.click();
    await expect(page.getByText('AUTO_APPROVED').first()).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Multi-User Identity', () => {
  test.setTimeout(180000);

  test('admin and dev-user see their own username labels', async ({ browser }) => {
    // Create separate browser contexts for each user (isolated cookies/storage)
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const devContext = await browser.newContext({ ignoreHTTPSErrors: true });

    const adminPage = await adminContext.newPage();
    const devPage = await devContext.newPage();

    const baseURL = process.env.KAGENTI_UI_URL || 'http://localhost:3000';

    try {
      // Login as admin
      await adminPage.goto(baseURL);
      await loginAs(adminPage, KEYCLOAK_USER, KEYCLOAK_PASSWORD);
      await navigateToWeatherChat(adminPage);

      // Login as dev-user
      await devPage.goto(baseURL);
      await loginAs(devPage, DEV_USER, DEV_PASSWORD);
      await navigateToWeatherChat(devPage);

      // Admin sends a message
      const adminInput = adminPage.getByPlaceholder('Type your message...');
      await adminInput.fill('Admin checking weather');
      await adminPage.getByRole('button', { name: /Send/i }).click();

      // Dev-user sends a message
      const devInput = devPage.getByPlaceholder('Type your message...');
      await devInput.fill('Dev checking weather');
      await devPage.getByRole('button', { name: /Send/i }).click();

      // Assert: admin sees "admin (you)" label
      const adminLabel = adminPage.locator('[data-testid^="message-username-user-"]');
      await expect(adminLabel.first()).toBeVisible({ timeout: 5000 });
      const adminText = await adminLabel.first().textContent();
      expect(adminText).toContain(KEYCLOAK_USER);
      expect(adminText).toContain('(you)');

      // Assert: dev-user sees "dev-user (you)" label
      const devLabel = devPage.locator('[data-testid^="message-username-user-"]');
      await expect(devLabel.first()).toBeVisible({ timeout: 5000 });
      const devText = await devLabel.first().textContent();
      expect(devText).toContain(DEV_USER);
      expect(devText).toContain('(you)');
    } finally {
      await adminContext.close();
      await devContext.close();
    }
  });

  test('dev-user identity persists across page reload', async ({ browser }) => {
    const devContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const devPage = await devContext.newPage();
    const baseURL = process.env.KAGENTI_UI_URL || 'http://localhost:3000';

    try {
      // Login as dev-user
      await devPage.goto(baseURL);
      await loginAs(devPage, DEV_USER, DEV_PASSWORD);
      await navigateToWeatherChat(devPage);

      // Send a message
      const chatInput = devPage.getByPlaceholder('Type your message...');
      await chatInput.fill('Dev persistence test');
      await devPage.getByRole('button', { name: /Send/i }).click();

      // Assert: dev-user label visible
      const devLabel = devPage.locator('[data-testid^="message-username-user-"]');
      await expect(devLabel.first()).toBeVisible({ timeout: 5000 });
      await expect(devLabel.first()).toContainText(DEV_USER);

      // Reload page — session should persist via Keycloak SSO
      await devPage.reload();
      await devPage.waitForLoadState('networkidle', { timeout: 30000 });

      // Navigate back to the chat
      await navigateToWeatherChat(devPage);

      // Assert: username label still shows dev-user after reload
      const chatInputAfter = devPage.getByPlaceholder('Type your message...');
      await chatInputAfter.fill('After reload');
      await devPage.getByRole('button', { name: /Send/i }).click();

      const reloadLabel = devPage.locator('[data-testid^="message-username-user-"]');
      await expect(reloadLabel.first()).toBeVisible({ timeout: 5000 });
      await expect(reloadLabel.first()).toContainText(DEV_USER);
    } finally {
      await devContext.close();
    }
  });
});

test.describe('Session Visibility RBAC', () => {
  test.setTimeout(180000);

  test('dev-user cannot see admin sessions in session history', async ({ browser }) => {
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const devContext = await browser.newContext({ ignoreHTTPSErrors: true });

    const adminPage = await adminContext.newPage();
    const devPage = await devContext.newPage();
    const baseURL = process.env.KAGENTI_UI_URL || 'http://localhost:3000';

    try {
      // Admin creates a chat session with a unique message
      await adminPage.goto(baseURL);
      await loginAs(adminPage, KEYCLOAK_USER, KEYCLOAK_PASSWORD);
      await navigateToWeatherChat(adminPage);

      const adminInput = adminPage.getByPlaceholder('Type your message...');
      const uniqueMsg = `Admin-RBAC-test-${Date.now()}`;
      await adminInput.fill(uniqueMsg);
      await adminPage.getByRole('button', { name: /Send/i }).click();

      // Wait for message to appear (confirms session was created)
      await expect(adminPage.getByText(uniqueMsg)).toBeVisible({ timeout: 10000 });

      // Dev-user logs in and navigates to the same agent chat
      await devPage.goto(baseURL);
      await loginAs(devPage, DEV_USER, DEV_PASSWORD);
      await navigateToWeatherChat(devPage);

      // Assert: dev-user's chat does NOT contain admin's unique message
      // This verifies session isolation between users
      await devPage.waitForTimeout(2000);
      const adminMsg = devPage.getByText(uniqueMsg);
      await expect(adminMsg).not.toBeVisible();
    } finally {
      await adminContext.close();
      await devContext.close();
    }
  });

  test('ns-admin can login and see correct role-based identity', async ({ browser }) => {
    const nsAdminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const nsAdminPage = await nsAdminContext.newPage();
    const baseURL = process.env.KAGENTI_UI_URL || 'http://localhost:3000';

    try {
      // Login as ns-admin
      await nsAdminPage.goto(baseURL);
      await loginAs(nsAdminPage, NS_ADMIN_USER, NS_ADMIN_PASSWORD);
      await navigateToWeatherChat(nsAdminPage);

      // Send a message
      const chatInput = nsAdminPage.getByPlaceholder('Type your message...');
      await chatInput.fill('ns-admin identity check');
      await nsAdminPage.getByRole('button', { name: /Send/i }).click();

      // Assert: ns-admin username label is visible
      const nsAdminLabel = nsAdminPage.locator('[data-testid^="message-username-user-"]');
      await expect(nsAdminLabel.first()).toBeVisible({ timeout: 5000 });
      const labelText = await nsAdminLabel.first().textContent();
      expect(labelText).toContain(NS_ADMIN_USER);
      expect(labelText).toContain('(you)');
    } finally {
      await nsAdminContext.close();
    }
  });
});
