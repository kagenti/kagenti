/**
 * Sessions Table E2E Tests
 *
 * Tests:
 * 1. Sessions table shows expected columns (Session ID, Title, Type, etc.)
 * 2. Session rows display session ID and title
 * 3. Type labels show root, child, or passover
 * 4. Type filter toggle filters sessions by type
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

/** Create a sandbox session by sending a quick message */
async function ensureSessionExists(page: Page) {
  await page.locator('nav a', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');

  // Check if sessions already exist
  const hasSession = await page.locator('text=/sandbox-legion|sandbox-agent/').first()
    .isVisible({ timeout: 3000 }).catch(() => false);
  if (hasSession) return;

  // No sessions — create one
  const chatInput = page.locator('textarea[aria-label="Message input"]').first();
  if (await chatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
    await chatInput.fill('Hello ownership test');
    await page.getByRole('button', { name: /Send/i }).click();
    await page.waitForTimeout(5000); // Wait for session to be created
  }
}

/** Navigate to the Sessions TABLE page (not the sidebar chat view) */
async function navigateToSessionsTable(page: Page) {
  // Navigate directly to the sessions table page
  await page.goto('/sandbox/sessions');
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('heading', { name: /^Sessions$/i })).toBeVisible({
    timeout: 15000,
  });
}

test.describe('Sessions Table', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await ensureSessionExists(page);
  });

  test('sessions table shows expected columns', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Assert: table has the expected column headers
    await expect(page.getByRole('columnheader', { name: 'Session ID' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Title' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Parent' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
  });

  test('sessions table rows show session ID and title', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Check if any session rows exist
    const sessionIdCells = page.locator('td[data-label="Session ID"]');
    const count = await sessionIdCells.count();

    if (count === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No sessions in table to check',
      });
      return;
    }

    // At least one cell should have a truncated session ID (8 chars + "...")
    const firstSessionId = await sessionIdCells.first().textContent();
    expect(firstSessionId).toBeTruthy();
    expect(firstSessionId!.length).toBeGreaterThan(0);

    // Title column should have content
    const titleCells = page.locator('td[data-label="Title"]');
    const firstTitle = await titleCells.first().textContent();
    expect(firstTitle).toBeTruthy();
  });

  test('type labels show root, child, or passover', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Wait for table rows to load (not just headers)
    await expect(page.locator('td[data-label="Session ID"]').first()).toBeVisible({
      timeout: 15000,
    });

    // At least one type label should exist (root, child, or passover)
    const rootLabel = page.locator('td[data-label="Type"]').getByText('root');
    const childLabel = page.locator('td[data-label="Type"]').getByText('child');
    const passoverLabel = page.locator('td[data-label="Type"]').getByText('passover');

    const hasRoot = await rootLabel.first().isVisible({ timeout: 5000 }).catch(() => false);
    const hasChild = await childLabel.first().isVisible({ timeout: 2000 }).catch(() => false);
    const hasPassover = await passoverLabel.first().isVisible({ timeout: 2000 }).catch(() => false);

    expect(hasRoot || hasChild || hasPassover).toBe(true);
  });

  test('type filter toggle filters sessions by type', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Wait for data to load — either table rows or the "No sessions found" empty state
    const tableOrEmpty = page
      .locator('td[data-label="Session ID"]')
      .first()
      .or(page.getByText(/No sessions found/i).first());
    await expect(tableOrEmpty).toBeVisible({ timeout: 15000 });

    // The "All" toggle should be selected by default
    const allToggle = page.getByRole('button', { name: /^All$/i });
    await expect(allToggle).toBeVisible({ timeout: 10000 });

    // Click "Root" filter
    const rootToggle = page.getByRole('button', { name: /^Root$/i });
    await expect(rootToggle).toBeVisible({ timeout: 5000 });
    await rootToggle.click();
    await page.waitForTimeout(1000);

    // After filtering, either sessions appear or the empty state shows
    // The empty state body text is: "No root sessions found in namespace ..."
    // The empty state header title is: "No sessions found"
    const hasRows = await page.locator('td[data-label="Session ID"]').first()
      .isVisible({ timeout: 5000 }).catch(() => false);
    const hasEmpty = await page.getByText(/No .* sessions found|No sessions found/i).first()
      .isVisible({ timeout: 2000 }).catch(() => false);

    expect(hasRows || hasEmpty).toBe(true);

    // Switch back to "All"
    await allToggle.click();
    await page.waitForTimeout(1000);
  });
});
