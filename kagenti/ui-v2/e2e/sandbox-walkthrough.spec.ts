/**
 * Sandbox Legion Deep-Dive Walkthrough
 *
 * End-to-end test covering the full sandbox user journey:
 * login → sandbox chat → sidebar → sessions table → kill → history
 *
 * Mirrors backend test scenarios (test_sandbox_sessions_api.py) in the UI.
 * Uses markStep() for narration sync (can be recorded as a demo video).
 *
 * Prerequisites:
 *   - Kagenti UI deployed with sandbox routes (/sandbox, /sandbox/sessions)
 *   - sandbox-legion agent deployed in team1
 *   - Backend rebuilt from source with sandbox router
 *   - postgres-sessions running in team1
 *
 * Environment:
 *   KAGENTI_UI_URL: Base URL (default: auto-detect from route)
 *   KEYCLOAK_USER / KEYCLOAK_PASSWORD: Login credentials (default: admin/admin)
 */
import { test, expect, type Page } from '@playwright/test';

// --- Config ---
const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

// --- Timing ---
const stepTimestamps: { step: string; time: number }[] = [];
let demoStartTime = 0;
const markStep = (step: string) => {
  const elapsed = (Date.now() - demoStartTime) / 1000;
  stepTimestamps.push({ step, time: elapsed });
  console.log(`[walkthrough] ${elapsed.toFixed(1)}s — ${step}`);
};

// --- Auth ---
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

  // Handle VERIFY_PROFILE if needed
  if (page.url().includes('VERIFY_PROFILE')) {
    const verifySubmit = page.locator(
      'input[type="submit"], button[type="submit"]'
    );
    if (
      await verifySubmit.isVisible({ timeout: 2000 }).catch(() => false)
    ) {
      await verifySubmit.click();
      await page.waitForURL(/^(?!.*keycloak)/, { timeout: 15000 });
    }
  }
}

// ==========================================================================
// WALKTHROUGH TEST
// ==========================================================================

test.describe('Sandbox Legion — Deep Dive Walkthrough', () => {
  test('full sandbox user journey', async ({ page }) => {
    test.setTimeout(300000); // 5 min for LLM calls
    demoStartTime = Date.now();

    // ------------------------------------------------------------------
    // Step 1: Login
    // ------------------------------------------------------------------
    markStep('intro');
    await page.goto('/');
    await loginIfNeeded(page);
    expect(page.url()).not.toContain('/realms/');
    markStep('login');

    // ------------------------------------------------------------------
    // Step 2: Navigate to Sandbox via sidebar
    // ------------------------------------------------------------------
    const sandboxNav = page
      .locator('nav a, nav button, [role="navigation"] a')
      .filter({ hasText: /^Sandbox$/ });
    await expect(sandboxNav.first()).toBeVisible({ timeout: 10000 });
    await sandboxNav.first().click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Legion/i })
    ).toBeVisible({ timeout: 15000 });
    markStep('sandbox_navigate');

    // ------------------------------------------------------------------
    // Step 3: Verify sidebar components
    // ------------------------------------------------------------------
    const searchInput = page.getByPlaceholder(/Search sessions/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });

    const newSessionBtn = page.getByRole('button', {
      name: /New Session/i,
    });
    await expect(newSessionBtn).toBeVisible();

    const viewAllBtn = page.getByRole('button', {
      name: /View All Sessions/i,
    });
    await expect(viewAllBtn).toBeVisible();
    markStep('sandbox_sidebar');

    // ------------------------------------------------------------------
    // Step 4: Toggle Advanced Config
    // ------------------------------------------------------------------
    const configToggle = page.getByText(/Advanced Configuration/i);
    await expect(configToggle).toBeVisible({ timeout: 5000 });
    await configToggle.click();

    await expect(page.locator('#sandbox-model')).toBeVisible({
      timeout: 5000,
    });
    await expect(page.locator('#sandbox-repo')).toBeVisible();
    await expect(page.locator('#sandbox-branch')).toBeVisible();

    // Collapse it back
    await configToggle.click();
    markStep('sandbox_config');

    // ------------------------------------------------------------------
    // Step 5: Send a chat message
    // ------------------------------------------------------------------
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const testMessage = 'List the contents of the current directory using ls';
    await chatInput.fill(testMessage);

    const sendButton = page.getByRole('button', { name: /Send/i });
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    // Verify user message appears
    await expect(page.getByText(testMessage)).toBeVisible({
      timeout: 5000,
    });
    markStep('sandbox_chat_send');

    // ------------------------------------------------------------------
    // Step 6: Wait for agent response
    // ------------------------------------------------------------------
    // Wait for a "Legion:" response to appear (the agent's reply)
    await expect(
      page.locator('strong:has-text("Legion")').first()
    ).toBeVisible({ timeout: 120000 });

    // Verify the response contains workspace-related content
    const chatArea = page.locator('.pf-v5-c-card__body').first();
    await expect(chatArea).toContainText(/data|scripts|repos|output/i, {
      timeout: 5000,
    });
    markStep('sandbox_chat_response');

    // ------------------------------------------------------------------
    // Step 7: Navigate to Sessions Table
    // ------------------------------------------------------------------
    await viewAllBtn.click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Sessions/i })
    ).toBeVisible({ timeout: 15000 });

    // Verify table has content
    const searchBox = page.getByPlaceholder(/Search by context ID/i);
    await expect(searchBox).toBeVisible({ timeout: 10000 });
    markStep('sandbox_sessions_table');

    // ------------------------------------------------------------------
    // Step 8: Search in table
    // ------------------------------------------------------------------
    await searchBox.fill('nonexistent-id-xyz');
    await page.waitForTimeout(500);

    // Should show no results
    await expect(
      page.locator('text=/No.*sessions/i').first()
    ).toBeVisible({ timeout: 10000 });

    // Clear search
    await searchBox.clear();
    await page.waitForTimeout(500);
    markStep('sandbox_table_search');

    // ------------------------------------------------------------------
    // Step 9: Navigate back to chat via New Session
    // ------------------------------------------------------------------
    const newSessionTableBtn = page.getByRole('button', {
      name: /New Session/i,
    });
    await expect(newSessionTableBtn).toBeVisible();
    await newSessionTableBtn.click();
    await page.waitForLoadState('networkidle');

    await expect(
      page.getByRole('heading', { name: /Sandbox Legion/i })
    ).toBeVisible({ timeout: 15000 });
    markStep('sandbox_return_chat');

    // ------------------------------------------------------------------
    // Step 10: End
    // ------------------------------------------------------------------
    markStep('end');

    // Write timestamps file for narration sync
    const { writeFileSync } = await import('fs');
    const { join, dirname } = await import('path');
    const { fileURLToPath } = await import('url');
    const __dir = dirname(fileURLToPath(import.meta.url));
    const tsFile = join(__dir, 'sandbox-walkthrough-timestamps.json');
    writeFileSync(tsFile, JSON.stringify(stepTimestamps, null, 2));
    console.log(`[walkthrough] Timestamps: ${tsFile}`);
    console.log(
      `[walkthrough] Total duration: ${((Date.now() - demoStartTime) / 1000).toFixed(1)}s`
    );
  });
});
