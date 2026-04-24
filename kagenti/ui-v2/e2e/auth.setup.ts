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
  // Retry navigation if the page doesn't load (CI cold start)
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.goto('/');
      await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
      break;
    } catch {
      if (attempt === 2) throw new Error('App failed to load after 3 attempts');
      await page.waitForTimeout(5000);
    }
  }

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
    await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
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

  // Wait for redirect back to the app (60s for CI cold start)
  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 60000 });

  // Wait for app to fully load — use domcontentloaded as minimum,
  // then verify navigation is visible (more reliable than domcontentloaded
  // which can timeout on slow CI runners with background API calls)
  await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
  await expect(page.locator('nav').or(page.getByRole('navigation')).first()).toBeVisible({
    timeout: 30000,
  });

  // Save authenticated state
  await page.context().storageState({ path: STORAGE_STATE });
});
