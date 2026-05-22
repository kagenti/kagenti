/**
 * Playwright Auth Setup
 *
 * Authenticates with Keycloak once and saves browser storage state
 * so all test specs run as an authenticated user.
 *
 * Environment variables:
 *   KEYCLOAK_USER: Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak password (default: admin)
 */
import { test as setup, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

export const STORAGE_STATE = path.join(__dirname, '../playwright/.auth/user.json');

setup('authenticate', async ({ page }) => {
  // Navigate to the app — Keycloak will intercept
  await page.goto('/');
  await page.waitForLoadState('networkidle', { timeout: 30000 });

  // Case 1: Already on Keycloak login page (login-required mode)
  const isKeycloakLogin = await page.locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    // Case 2: App loaded with "Sign In" button (check-sso mode)
    const signInButton = page.getByRole('button', { name: /Sign In/i });
    const hasSignIn = await signInButton.isVisible({ timeout: 5000 }).catch(() => false);

    if (!hasSignIn) {
      // No auth needed — save empty state and return
      await page.context().storageState({ path: STORAGE_STATE });
      return;
    }

    await signInButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }

  // Fill Keycloak credentials
  const usernameField = page.locator('input[name="username"]').first();
  const passwordField = page.locator('input[name="password"]').first();
  const submitButton = page.locator('#kc-login, button[type="submit"], input[type="submit"]').first();

  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await usernameField.fill(KEYCLOAK_USER);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  await passwordField.pressSequentially(KEYCLOAK_PASSWORD, { delay: 20 });
  await page.waitForTimeout(300);
  await submitButton.click();

  // Wait for redirect back to the app
  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');

  // Verify we're logged in — sidebar navigation should be visible
  await expect(page.locator('nav').or(page.getByRole('navigation')).first()).toBeVisible({
    timeout: 10000,
  });

  // Save authenticated state
  await page.context().storageState({ path: STORAGE_STATE });
});
