/**
 * Shared authentication helper for Playwright E2E tests.
 *
 * Handles Keycloak login across all environments:
 * - Kind (check-sso mode): App loads with "Sign In" button
 * - HyperShift (login-required mode): Direct redirect to Keycloak
 * - No auth: No login elements visible — no-op
 */
import type { Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

export async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('domcontentloaded', { timeout: 30000 });

  // Race: wait for EITHER authenticated nav (Agents/Tools visible) OR a login
  // prompt (Keycloak form or Sign In button). OIDC check-sso can take 5-15s
  // on HyperShift clusters, so 5s was too short for the old approach.
  const authNav = page.locator('nav a, nav button', { hasText: /Agents|Tools/ }).first();
  const signInButton = page.getByRole('button', { name: /Sign In/i });
  const keycloakForm = page.locator('#kc-form-login, input[name="username"]').first();

  const state = await Promise.race([
    authNav.waitFor({ state: 'visible', timeout: 20000 }).then(() => 'authenticated' as const),
    signInButton.waitFor({ state: 'visible', timeout: 20000 }).then(() => 'signIn' as const),
    keycloakForm.waitFor({ state: 'visible', timeout: 20000 }).then(() => 'keycloak' as const),
  ]).catch(() => 'none' as const);

  if (state === 'authenticated' || state === 'none') return;

  if (state === 'signIn') {
    await signInButton.click();
    await page.waitForLoadState('domcontentloaded', { timeout: 30000 });
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
  await page.waitForLoadState('domcontentloaded');
}
