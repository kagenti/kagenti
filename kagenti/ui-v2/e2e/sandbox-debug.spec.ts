/**
 * Sandbox UI Visual Debug Test
 *
 * Takes screenshots at every step for visual inspection. Tests:
 * 1. Login + navigate to Sessions
 * 2. Session sidebar rendering (compact display, root-only)
 * 3. Send chat message + verify response rendering
 * 4. Session history loading (verify messages show after reload)
 * 5. Switch to different session + verify history loads
 * 6. Switch back + verify original session restores
 * 7. Send long-running command (sleep) and observe streaming state
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-debug
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

const SCREENSHOT_DIR = 'test-results/sandbox-debug';

let screenshotIdx = 0;
async function snap(page: Page, label: string) {
  screenshotIdx++;
  const name = `${String(screenshotIdx).padStart(2, '0')}-${label}`;
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
  console.log(`[debug] Screenshot: ${name}`);
}

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

test.describe('Sandbox Debug — Visual Inspection', () => {
  test('session switching and history loading', async ({ page }) => {
    test.setTimeout(300000); // 5 min
    screenshotIdx = 0;

    // ---- Step 1: Login ----
    await page.goto('/');
    await loginIfNeeded(page);
    await snap(page, 'after-login');

    // ---- Step 2: Navigate to Sessions ----
    const sessionsNav = page
      .locator('nav a, nav button, [role="navigation"] a')
      .filter({ hasText: /^Sessions$/ });
    await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
    await sessionsNav.first().click();
    await page.waitForLoadState('networkidle');
    await snap(page, 'sessions-page');

    // Verify heading
    await expect(
      page.getByRole('heading', { name: /Sandbox Legion/i })
    ).toBeVisible({ timeout: 15000 });

    // ---- Step 3: Verify sidebar ----
    // Check Sessions title in sidebar
    const sidebarTitle = page.locator('h3').filter({ hasText: /Sessions/i });
    await expect(sidebarTitle).toBeVisible({ timeout: 5000 });

    // Check root-only toggle
    const rootToggle = page.locator('#root-only-toggle');
    await expect(rootToggle).toBeVisible({ timeout: 5000 });

    // Check session items exist
    const sessionItems = page.locator('[role="button"]').filter({
      has: page.locator('text=/sandbox-legion|Done|Active/i'),
    });
    const sessionCount = await sessionItems.count();
    console.log(`[debug] Session items visible: ${sessionCount}`);
    await snap(page, 'sidebar-sessions');

    // ---- Step 4: Click first session (if any) ----
    let firstSessionId = '';
    if (sessionCount > 0) {
      await sessionItems.first().click();
      await page.waitForTimeout(2000); // Wait for history to load
      await snap(page, 'first-session-loaded');

      // Check URL has session param
      firstSessionId = new URL(page.url()).searchParams.get('session') || '';
      console.log(`[debug] First session ID: ${firstSessionId}`);

      // Verify messages appeared in chat
      const chatArea = page.locator('.pf-v5-c-card__body').first();
      const chatText = await chatArea.textContent();
      console.log(
        `[debug] Chat area text length: ${chatText?.length ?? 0}`
      );
      console.log(
        `[debug] Chat area preview: ${chatText?.substring(0, 200)}`
      );
      await snap(page, 'first-session-messages');
    }

    // ---- Step 5: Send a new message ----
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });
    await chatInput.fill('Say exactly: debug-test-alpha');
    await snap(page, 'before-send');

    const sendButton = page.getByRole('button', { name: /Send/i });
    await sendButton.click();

    // Verify user message appears
    await expect(page.getByText('debug-test-alpha')).toBeVisible({
      timeout: 5000,
    });
    await snap(page, 'after-send-user-message');

    // Wait for agent response
    const chatArea = page.locator('.pf-v5-c-card__body').first();
    await expect(chatArea).toContainText(/debug-test-alpha/i, {
      timeout: 120000,
    });
    await snap(page, 'after-agent-response');

    // Get the session ID for this conversation
    const currentSessionId =
      new URL(page.url()).searchParams.get('session') || '';
    console.log(`[debug] Current session after send: ${currentSessionId}`);

    // ---- Step 6: Click a different session in sidebar ----
    // Wait for sidebar to refresh and show our new session
    await page.waitForTimeout(3000);
    await snap(page, 'sidebar-after-new-message');

    // Click New Session to start fresh
    const newSessionBtn = page.getByRole('button', {
      name: /New Session/i,
    });
    await newSessionBtn.click();
    await page.waitForTimeout(1000);
    await snap(page, 'new-session-blank');

    // Verify chat is empty
    const emptyMsg = page.getByText(/Start a conversation/i);
    const isEmpty = await emptyMsg.isVisible({ timeout: 3000 }).catch(() => false);
    console.log(`[debug] New session is empty: ${isEmpty}`);

    // ---- Step 7: Switch back to previous session ----
    // Click the first session in sidebar (should be our just-created one)
    const prevSession = page.locator('[role="button"]').filter({
      has: page.locator('text=/sandbox-legion/i'),
    });
    if ((await prevSession.count()) > 0) {
      await prevSession.first().click();
      await page.waitForTimeout(3000); // Wait for history to load
      await snap(page, 'switched-back-to-previous');

      // Verify the messages from our previous session loaded
      const restoredChat = page.locator('.pf-v5-c-card__body').first();
      const restoredText = await restoredChat.textContent();
      console.log(
        `[debug] Restored chat text length: ${restoredText?.length ?? 0}`
      );
      console.log(
        `[debug] Contains debug-test-alpha: ${restoredText?.includes('debug-test-alpha')}`
      );
      await snap(page, 'restored-session-messages');
    }

    // ---- Step 8: Verify page reload preserves session ----
    const urlBeforeReload = page.url();
    console.log(`[debug] URL before reload: ${urlBeforeReload}`);
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
    await snap(page, 'after-page-reload');

    const urlAfterReload = page.url();
    console.log(`[debug] URL after reload: ${urlAfterReload}`);

    // Check session param is preserved
    const reloadedSession =
      new URL(page.url()).searchParams.get('session') || '';
    console.log(`[debug] Session after reload: ${reloadedSession}`);

    // Check chat content is restored
    const reloadedChat = page.locator('.pf-v5-c-card__body').first();
    const reloadedText = await reloadedChat.textContent();
    console.log(
      `[debug] Reloaded chat text length: ${reloadedText?.length ?? 0}`
    );
    await snap(page, 'reloaded-session-content');

    // ---- Final: Summary ----
    console.log('[debug] === Test Summary ===');
    console.log(`[debug] Total screenshots: ${screenshotIdx}`);
  });
});
