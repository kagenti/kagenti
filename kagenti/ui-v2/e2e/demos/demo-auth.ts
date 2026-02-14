/**
 * Shared Keycloak authentication helper for demo tests.
 *
 * Works across all environments:
 * - Kind (community Keycloak, check-sso mode with Sign In button)
 * - HyperShift (Red Hat build of Keycloak, login-required mode)
 * - No auth (graceful skip)
 *
 * Environment variables:
 *   KEYCLOAK_USER     - Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD - Keycloak password (default: admin)
 *   KEYCLOAK_PASS     - Alias for KEYCLOAK_PASSWORD (backward compat)
 */
import { Page, expect } from '@playwright/test';

export const KC_USER = process.env.KEYCLOAK_USER || 'admin';
export const KC_PASS = process.env.KEYCLOAK_PASSWORD || process.env.KEYCLOAK_PASS || 'admin';

/**
 * Perform Keycloak login on the current page.
 *
 * @param page - Playwright page
 * @param demoClick - Optional demo click function (with cursor animation).
 *                    If not provided, uses regular locator.click().
 */
export async function demoLogin(
  page: Page,
  demoClick?: (locator: any, description?: string) => Promise<void>,
) {
  const click = demoClick || (async (loc: any) => loc.click());

  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});

  // Case 1: Already on Keycloak login page (HyperShift login-required mode)
  const isKeycloakLogin = await page.locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    // Case 2: App loaded with "Sign In" button (Kind check-sso mode)
    const loginButton = page.getByRole('button', { name: /sign in|login|log in/i })
      .or(page.getByRole('link', { name: /sign in|login|log in/i }));

    const hasLoginButton = await loginButton.first().isVisible({ timeout: 5000 }).catch(() => false);

    if (!hasLoginButton) {
      // No login needed — auth disabled or already authenticated
      console.log('[demo] No login button — auth disabled or already authenticated');
      return;
    }

    await click(loginButton.first(), 'Sign In button');

    await page.waitForURL(
      (url) => url.toString().includes('/realms/'),
      { timeout: 15000 }
    );
  }

  // Now on Keycloak login page — fill credentials
  // Selectors work for both community Keycloak and Red Hat build
  const usernameField = page.locator('#username, input[name="username"]').first();
  const passwordField = page.locator('#password, input[name="password"]').first();

  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForTimeout(500);
  await usernameField.fill(KC_USER);
  await page.waitForTimeout(500);

  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  // Use pressSequentially for password — Red Hat Keycloak ignores fill()
  await passwordField.pressSequentially(KC_PASS, { delay: 20 });
  await page.waitForTimeout(500);

  await click(page.locator('#kc-login, button[type="submit"], input[type="submit"]').first(), 'Keycloak Sign In');

  // Handle VERIFY_PROFILE page (first login on HyperShift)
  await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
  if (page.url().includes('VERIFY_PROFILE') || page.url().includes('required-action')) {
    console.log('[demo] Handling VERIFY_PROFILE page');
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
  console.log('[demo] Login successful');
}
