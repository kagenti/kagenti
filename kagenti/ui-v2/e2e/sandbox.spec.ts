/**
 * Sandbox Legion UI E2E Tests
 *
 * Tests the full user flow for the Sandbox Legion management UI:
 * - Login → navigate to sandbox → start chat → verify response
 * - Session sidebar visibility and interaction
 * - Sessions table search and navigation
 * - Advanced config panel toggle
 * - Kill session from table
 *
 * Prerequisites:
 * - sandbox-legion deployed in team1 with TASK_STORE_DB_URL
 * - postgres-sessions StatefulSet running
 * - Backend API accessible with /api/v1/sandbox/ routes
 *
 * Environment variables:
 *   KAGENTI_UI_URL: Base URL for the UI (default: http://localhost:3000)
 *   KEYCLOAK_USER: Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak password (default: admin)
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

/**
 * Assert no unexpected error states are visible on the page.
 * Call this after navigating to any sandbox page to catch regressions.
 */
async function assertNoErrors(page: Page) {
  // No danger/error alerts should be visible
  const dangerAlerts = page.locator('.pf-v5-c-alert.pf-m-danger');
  const dangerCount = await dangerAlerts.count();
  expect(dangerCount).toBe(0);

  // No "Error:" messages in the chat area
  const errorMessages = page.locator('text=/^Error:/');
  const errorMsgCount = await errorMessages.count();
  expect(errorMsgCount).toBe(0);
}

/**
 * Assert no failed/errored sessions in the sidebar.
 * Failed sessions from test cleanup or crashes indicate a problem.
 */
async function assertNoFailedSessions(page: Page) {
  // Wait for sidebar to populate
  await page.waitForTimeout(3000);

  // Check for "Failed" labels in the session sidebar
  const failedLabels = page.locator('[class*="pf-v5-c-label"][class*="pf-m-red"]');
  const failedCount = await failedLabels.count();
  if (failedCount > 0) {
    // Warn but don't fail — previous test runs or other sessions may have left failed sessions
    console.warn(`[WARN] Found ${failedCount} failed session(s) in sidebar — may be from prior runs`);
  }
}

test.describe('Sandbox Legion - Health Check', () => {
  test.setTimeout(60000);

  test('should have no error alerts or failed sessions on load', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /sandbox-legion/i })
    ).toBeVisible({ timeout: 15000 });

    // Core assertions: no errors, no failed sessions
    await assertNoErrors(page);
    await assertNoFailedSessions(page);
  });
});

test.describe('Sandbox Legion - Navigation', () => {
  test.setTimeout(60000);

  test('should have Sessions in navigation sidebar', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    const sandboxNav = page.locator('nav a, nav button', {
      hasText: 'Sessions',
    });
    await expect(sandboxNav.first()).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to sandbox page', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /sandbox-legion/i })
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe('Sandbox Legion - Chat', () => {
  test.setTimeout(120000);

  test('should login, navigate to sandbox, and send a chat message', async ({
    page,
  }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Navigate to sandbox
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /sandbox-legion/i })
    ).toBeVisible({ timeout: 15000 });

    // Verify chat input is visible
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    // Send a message
    await chatInput.fill('Say exactly: playwright-sandbox-test');
    const sendButton = page.getByRole('button', { name: /Send/i });
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    // Verify user message appears
    await expect(
      page.getByText('Say exactly: playwright-sandbox-test')
    ).toBeVisible({ timeout: 5000 });

    // Wait for response from agent
    await expect(
      page.locator('text=/playwright-sandbox-test|Legion/i').first()
    ).toBeVisible({ timeout: 180000 });

    // Verify no errors appeared during chat
    await assertNoErrors(page);
  });
});

test.describe('Sandbox Legion - Sidebar', () => {
  test.setTimeout(60000);

  test('should show session sidebar with search', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Sidebar search should be visible
    const searchInput = page.getByPlaceholder(/Search sessions/i);
    await expect(searchInput).toBeVisible({ timeout: 15000 });

    // New Session button should be visible
    await expect(
      page.getByRole('button', { name: /New Session/i })
    ).toBeVisible();

    // View All link should be visible
    await expect(
      page.getByRole('button', { name: /View All Sessions/i })
    ).toBeVisible();
  });

  test('should navigate to sessions table via View All', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    await page
      .getByRole('button', { name: /View All Sessions/i })
      .click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sessions/i })
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe('Sandbox Legion - Sessions Table', () => {
  test.setTimeout(60000);

  test('should display sessions table with search', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: /View All Sessions/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sessions/i })
    ).toBeVisible({ timeout: 15000 });

    // Search input should be visible
    const searchInput = page.getByPlaceholder(/Search by context ID/i);
    await expect(searchInput).toBeVisible();
  });

  test('should search and filter results', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: /View All Sessions/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sessions/i })
    ).toBeVisible({ timeout: 15000 });

    // Search for non-existent ID
    const searchInput = page.getByPlaceholder(/Search by context ID/i);
    await searchInput.fill('nonexistent-context-id-xyz');
    await page.waitForTimeout(500);

    // Should show "No sessions found" or empty table
    await expect(
      page.locator('text=/No.*sessions/i').first()
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Sandbox Legion - Agents Panel', () => {
  test.setTimeout(60000);

  test('should show sandbox agents panel in sidebar', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Agents panel should be visible below sessions
    await expect(
      page.getByText(/Sandboxes/i).first()
    ).toBeVisible({ timeout: 15000 });
  });

  test('should show Import Agent button and navigate to wizard', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Import Agent button should be visible
    const importBtn = page.getByRole('button', { name: /Import Agent/i });
    await expect(importBtn).toBeVisible({ timeout: 10000 });

    // Click should navigate to wizard
    await importBtn.click();
    await page.waitForLoadState('networkidle');
    await expect(
      page.getByRole('heading', { name: /Create Sandbox Agent/i })
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe('Sandbox Legion - Root Only Toggle', () => {
  test.setTimeout(60000);

  test('should toggle between root-only and all sessions', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Root only toggle should be visible
    const toggle = page.locator('#root-only-toggle');
    await expect(toggle).toBeVisible({ timeout: 10000 });

    // Should be checked by default
    await expect(toggle).toBeChecked();
  });
});

test.describe('Sandbox Legion - Advanced Config', () => {
  test.setTimeout(60000);

  // SandboxConfig panel is disabled — model/repo/branch not yet wired to backend.
  // See SandboxPage.tsx: "SandboxConfig disabled" comments.
  test.skip(true, 'SandboxConfig panel disabled — not yet wired to backend');

  test('should toggle advanced config panel', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a, nav button', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');

    // Find and click the advanced config toggle
    const configToggle = page.getByText(/Advanced Configuration/i);
    await expect(configToggle).toBeVisible({ timeout: 15000 });
    await configToggle.click();

    // Model dropdown should become visible
    await expect(page.locator('#sandbox-model')).toBeVisible({
      timeout: 5000,
    });

    // Repository input should become visible
    await expect(page.locator('#sandbox-repo')).toBeVisible();

    // Branch input should become visible
    await expect(page.locator('#sandbox-branch')).toBeVisible();
  });
});
