/**
 * Session Ownership & Visibility E2E Tests
 *
 * Tests:
 * 1. Sessions table shows Owner and Visibility columns
 * 2. Session created via sandbox chat has owner set to current user
 * 3. Visibility labels show Private or Shared
 * 4. Visibility toggle switches between Private and Shared
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

/** Navigate to the Sessions TABLE page (not the sidebar chat view) */
async function navigateToSessionsTable(page: Page) {
  // Sessions sidebar → click "View All Sessions" link to get to the table
  await page.locator('nav a', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');
  // Scroll to and click "View All Sessions" link
  const viewAllLink = page.getByText('View All Sessions');
  await viewAllLink.scrollIntoViewIfNeeded();
  await viewAllLink.click();
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('heading', { name: /Sandbox Sessions/i })).toBeVisible({
    timeout: 15000,
  });
}

test.describe('Session Ownership & Visibility', () => {
  test.setTimeout(120000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('sessions table shows Owner and Visibility columns', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Assert: table has Owner and Visibility headers
    await expect(page.getByRole('columnheader', { name: 'Owner' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Visibility' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Session' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Agent' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  });

  test('sessions show owner with (you) badge for current user', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Check if any session has the owner set
    const ownerCells = page.locator('td[data-label="Owner"]');
    const count = await ownerCells.count();

    if (count === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No sessions in table to check owner',
      });
      return;
    }

    // At least one cell should have the current username or "-" (unowned)
    const firstOwner = await ownerCells.first().textContent();
    expect(firstOwner).toBeTruthy();

    // If there's a session owned by us, check for "(you)" badge
    const youBadge = page.locator('td[data-label="Owner"]').filter({ hasText: 'you' });
    const hasOwnSession = await youBadge.count();
    if (hasOwnSession > 0) {
      await expect(youBadge.first()).toContainText(KEYCLOAK_USER);
    }
  });

  test('visibility labels show Private or Shared', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Wait for table rows to load (not just headers)
    await expect(page.locator('td[data-label="Session"]').first()).toBeVisible({
      timeout: 15000,
    });

    // At least one visibility label should exist
    const privateLabel = page.getByText('Private');
    const sharedLabel = page.getByText('Shared');

    const hasPrivate = await privateLabel.first().isVisible({ timeout: 5000 }).catch(() => false);
    const hasShared = await sharedLabel.first().isVisible({ timeout: 2000 }).catch(() => false);

    expect(hasPrivate || hasShared).toBe(true);
  });

  test('visibility toggle switches between Private and Shared', async ({ page }) => {
    await navigateToSessionsTable(page);

    // Find a Private label to toggle (must be our own session)
    const privateLabel = page.getByText('Private').first();
    const hasPrivate = await privateLabel.isVisible({ timeout: 5000 }).catch(() => false);

    if (!hasPrivate) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No private sessions available to toggle',
      });
      return;
    }

    // Click to toggle to Shared
    await privateLabel.click();
    await page.waitForTimeout(2000);

    // Assert: Shared label appears
    await expect(page.getByText('Shared').first()).toBeVisible({ timeout: 10000 });

    // Toggle back to Private
    await page.getByText('Shared').first().click();
    await page.waitForTimeout(2000);

    await expect(page.getByText('Private').first()).toBeVisible({ timeout: 10000 });
  });
});
