/**
 * Shared Keycloak authentication helper for E2E tests.
 *
 * Handles login across all environments:
 * - Kind (community Keycloak, check-sso mode with Sign In button)
 * - HyperShift/OpenShift (Red Hat build of Keycloak, login-required mode)
 * - No auth (graceful no-op)
 *
 * Environment variables:
 *   KEYCLOAK_USER     - Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD - Keycloak password (default: admin)
 */
import { Page, expect } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || process.env.KEYCLOAK_PASS || 'admin';

/**
 * Handle Keycloak login on the current page if needed.
 *
 * Kind (check-sso mode): App loads with "Sign In" button -> click -> Keycloak form
 * HyperShift (login-required mode): Direct redirect to Keycloak form
 * No auth: No login elements visible -> no-op
 */
export async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});

  // Case 1: Already on Keycloak login page (HyperShift login-required mode)
  const isKeycloakLogin = await page.locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    // Case 2: App loaded with "Sign In" button (Kind check-sso mode)
    const signInButton = page.getByRole('button', { name: /sign in|login|log in/i })
      .or(page.getByRole('link', { name: /sign in|login|log in/i }));
    const hasSignIn = await signInButton.first().isVisible({ timeout: 5000 }).catch(() => false);

    if (!hasSignIn) {
      // No login needed — either auth disabled or already authenticated
      return;
    }

    await signInButton.first().click();
    await page.waitForURL(
      (url) => url.toString().includes('/realms/'),
      { timeout: 15000 }
    );
  }

  // Now on Keycloak login page — fill credentials
  const usernameField = page.locator('#username, input[name="username"]').first();
  const passwordField = page.locator('#password, input[name="password"]').first();

  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await usernameField.fill(KEYCLOAK_USER);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  // Use pressSequentially for password — some Keycloak builds ignore fill()
  await passwordField.pressSequentially(KEYCLOAK_PASSWORD, { delay: 20 });
  await page.waitForTimeout(300);

  await page.locator('#kc-login, button[type="submit"], input[type="submit"]').first().click();

  // Handle VERIFY_PROFILE page (first login on HyperShift)
  await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
  if (page.url().includes('VERIFY_PROFILE') || page.url().includes('required-action')) {
    const emailField = page.locator('#email');
    if (await emailField.isVisible({ timeout: 2000 }).catch(() => false)) {
      if (!(await emailField.inputValue())) await emailField.fill('admin@kagenti.local');
    }
    const firstNameField = page.locator('#firstName');
    if (await firstNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
      if (!(await firstNameField.inputValue())) await firstNameField.fill('Admin');
    }
    const lastNameField = page.locator('#lastName');
    if (await lastNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
      if (!(await lastNameField.inputValue())) await lastNameField.fill('User');
    }
    const submitBtn = page.locator('input[type="submit"], button[type="submit"]');
    if (await submitBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await submitBtn.click();
    }
  }

  // Wait for redirect back to the app
  await page.waitForURL(
    (url) => !url.toString().includes('/realms/'),
    { timeout: 30000 }
  );
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

  // Verify we're not stuck on Keycloak
  expect(page.url()).not.toContain('/realms/');
}
