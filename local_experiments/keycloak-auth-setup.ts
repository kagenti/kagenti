/**
 * Playwright Global Setup: Keycloak Authentication
 *
 * The Kagenti UI uses keycloak-js with `onLoad: 'check-sso'`, meaning:
 *   - The UI loads without forcing login
 *   - A "Sign In" / "Login" button is shown
 *   - User must click it to trigger the Keycloak redirect
 *
 * This setup simulates that flow:
 *   1. Navigate to UI
 *   2. Wait for page to load
 *   3. Click the Sign In / Login button
 *   4. Fill Keycloak credentials
 *   5. Wait for redirect back to UI
 *   6. Save browser state for reuse by tests
 *
 * Environment variables:
 *   KEYCLOAK_USER   - Keycloak username (default: admin)
 *   KEYCLOAK_PASS   - Keycloak password (default: admin)
 *   KAGENTI_UI_URL  - Base URL of the Kagenti UI
 *   AUTH_STATE_PATH  - Where to save the browser state JSON
 */
import { chromium, type FullConfig } from '@playwright/test';

const AUTH_STATE_PATH = process.env.AUTH_STATE_PATH || require('path').join(__dirname, '.auth', 'state.json');

async function globalSetup(config: FullConfig) {
  const baseURL = process.env.KAGENTI_UI_URL;
  if (!baseURL) {
    console.log('[auth-setup] KAGENTI_UI_URL not set, skipping auth setup');
    return;
  }

  const user = process.env.KEYCLOAK_USER || 'admin';
  const pass = process.env.KEYCLOAK_PASS || 'admin';

  console.log(`[auth-setup] Navigating to ${baseURL}...`);

  const browser = await chromium.launch();
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  try {
    // Navigate to the UI and wait for it to fully load
    await page.goto(baseURL, { waitUntil: 'networkidle', timeout: 30000 });

    console.log(`[auth-setup] Page loaded: ${page.url()}`);

    // Look for a Sign In / Login button (the UI uses check-sso, so login is manual)
    const loginButton = page.getByRole('button', { name: /sign in|login|log in/i });
    const loginLink = page.getByRole('link', { name: /sign in|login|log in/i });
    const loginLocator = loginButton.or(loginLink);

    // Check if auth is enabled (login button present)
    const hasLoginButton = await loginLocator.first().isVisible({ timeout: 5000 }).catch(() => false);

    if (!hasLoginButton) {
      console.log('[auth-setup] No login button found — auth may be disabled');
      await context.storageState({ path: AUTH_STATE_PATH });
      console.log(`[auth-setup] State saved (no auth) to ${AUTH_STATE_PATH}`);
      await browser.close();
      return;
    }

    console.log('[auth-setup] Login button found, clicking...');
    await loginLocator.first().click();

    // Wait for Keycloak login page
    console.log('[auth-setup] Waiting for Keycloak login page...');
    await page.waitForURL(
      (url) => {
        const href = url.toString();
        return href.includes('/realms/') || href.includes('/protocol/openid-connect/');
      },
      { timeout: 30000 }
    );

    console.log(`[auth-setup] Keycloak login page: ${page.url()}`);

    // Wait for the login form
    await page.waitForSelector('#username', { timeout: 15000 });

    // Fill credentials
    await page.fill('#username', user);
    await page.fill('#password', pass);

    console.log(`[auth-setup] Logging in as: ${user}`);
    await page.click('#kc-login');

    // After clicking login, wait a moment and check what page we're on
    await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
    const postLoginURL = page.url();
    console.log(`[auth-setup] Post-login URL: ${postLoginURL}`);

    // Handle Keycloak required action pages (update profile, verify email, terms, etc.)
    // These show up at login-actions/required-action or login-actions/authenticate
    if (postLoginURL.includes('login-actions')) {
      console.log('[auth-setup] Keycloak intermediate page detected');

      // Take screenshot for debugging
      const screenshotPath = AUTH_STATE_PATH.replace('state.json', 'keycloak-action.png');
      await page.screenshot({ path: screenshotPath });
      console.log(`[auth-setup] Screenshot saved: ${screenshotPath}`);

      // Check for error message first (invalid credentials)
      const errorMessage = page.locator('.alert-error, .kc-feedback-text, #input-error');
      if (await errorMessage.isVisible({ timeout: 2000 }).catch(() => false)) {
        const errorText = await errorMessage.textContent() || 'unknown error';
        console.error(`[auth-setup] Keycloak error: ${errorText.trim()}`);
      }

      // Handle VERIFY_PROFILE / Update Account Information page
      if (postLoginURL.includes('VERIFY_PROFILE') || postLoginURL.includes('required-action')) {
        console.log('[auth-setup] Profile verification page — filling required fields...');

        // Fill email if empty
        const emailField = page.locator('#email');
        if (await emailField.isVisible({ timeout: 2000 }).catch(() => false)) {
          const emailValue = await emailField.inputValue();
          if (!emailValue) {
            await emailField.fill('admin@kagenti.local');
          }
        }

        // Fill first name if empty
        const firstNameField = page.locator('#firstName');
        if (await firstNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          const fnValue = await firstNameField.inputValue();
          if (!fnValue) {
            await firstNameField.fill('Admin');
          }
        }

        // Fill last name if empty
        const lastNameField = page.locator('#lastName');
        if (await lastNameField.isVisible({ timeout: 1000 }).catch(() => false)) {
          const lnValue = await lastNameField.inputValue();
          if (!lnValue) {
            await lastNameField.fill('User');
          }
        }

        // Click Submit
        const submitButton = page.locator('input[type="submit"], button[type="submit"]');
        if (await submitButton.isVisible({ timeout: 2000 }).catch(() => false)) {
          console.log('[auth-setup] Submitting profile form...');
          await submitButton.click();
          await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
          console.log(`[auth-setup] After profile submit: ${page.url()}`);
        }
      }
    }

    // Wait for redirect back to UI
    try {
      await page.waitForURL(
        (url) => {
          const href = url.toString();
          return href.startsWith(baseURL) && !href.includes('/realms/');
        },
        { timeout: 30000 }
      );
    } catch {
      console.error(`[auth-setup] Still not redirected back to UI. Current URL: ${page.url()}`);
      const screenshotPath = AUTH_STATE_PATH.replace('state.json', 'auth-debug.png');
      await page.screenshot({ path: screenshotPath });
      console.error(`[auth-setup] Debug screenshot: ${screenshotPath}`);
      throw new Error('Keycloak login redirect did not complete');
    }

    // Wait for the UI to settle after login
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {
      console.log('[auth-setup] networkidle timeout after login, continuing');
    });

    console.log(`[auth-setup] Login successful! URL: ${page.url()}`);

    // Save authenticated browser state (cookies + localStorage with tokens)
    await context.storageState({ path: AUTH_STATE_PATH });
    console.log(`[auth-setup] Authenticated state saved to ${AUTH_STATE_PATH}`);

  } catch (error) {
    console.error(`[auth-setup] Authentication failed: ${error}`);
    console.error('[auth-setup] Tests will run without authentication');
    try {
      await context.storageState({ path: AUTH_STATE_PATH });
    } catch {
      // Ignore save errors
    }
  } finally {
    await browser.close();
  }
}

export default globalSetup;
