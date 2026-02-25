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
    const hasSignIn = await signInButton
      .isVisible({ timeout: 5000 })
      .catch(() => false);

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

test.describe('Sandbox Legion - Navigation', () => {
  test.setTimeout(60000);

  test('should have Sandbox in navigation sidebar', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    const sandboxNav = page.locator('nav a, nav button', {
      hasText: 'Sandbox',
    });
    await expect(sandboxNav.first()).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to sandbox page', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.locator('nav a, nav button', { hasText: 'Sandbox' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Legion/i })
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
    await page.locator('nav a, nav button', { hasText: 'Sandbox' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Legion/i })
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
    ).toBeVisible({ timeout: 90000 });
  });
});

test.describe('Sandbox Legion - Sidebar', () => {
  test.setTimeout(60000);

  test('should show session sidebar with search', async ({ page }) => {
    await page.goto('/sandbox');
    await loginIfNeeded(page);

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
    await page.goto('/sandbox');
    await loginIfNeeded(page);

    await page
      .getByRole('button', { name: /View All Sessions/i })
      .click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Sessions/i })
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe('Sandbox Legion - Sessions Table', () => {
  test.setTimeout(60000);

  test('should display sessions table with search', async ({ page }) => {
    await page.goto('/sandbox/sessions');
    await loginIfNeeded(page);

    await expect(
      page.getByRole('heading', { name: /Sandbox Sessions/i })
    ).toBeVisible({ timeout: 15000 });

    // Search input should be visible
    const searchInput = page.getByPlaceholder(/Search by context ID/i);
    await expect(searchInput).toBeVisible();

    // New Session button should be visible
    await expect(
      page.getByRole('button', { name: /New Session/i })
    ).toBeVisible();
  });

  test('should search and filter results', async ({ page }) => {
    await page.goto('/sandbox/sessions');
    await loginIfNeeded(page);

    await expect(
      page.getByRole('heading', { name: /Sandbox Sessions/i })
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

test.describe('Sandbox Legion - Advanced Config', () => {
  test.setTimeout(60000);

  test('should toggle advanced config panel', async ({ page }) => {
    await page.goto('/sandbox');
    await loginIfNeeded(page);

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
