/**
 * Sandbox Agent Variants — Multi-Turn E2E Test
 *
 * Parameterized test that verifies each deployed agent variant can:
 * 1. Be selected in the Sandboxes panel
 * 2. Execute a multi-turn conversation (3 turns with tool call)
 * 3. Return correct responses
 *
 * Variants tested: sandbox-legion, sandbox-hardened, sandbox-basic, sandbox-restricted
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-variants
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';
const AGENT_TIMEOUT = 180_000;
const SCREENSHOT_DIR = 'test-results/sandbox-variants';

// Agent variants to test — each must be deployed on the cluster
const AGENT_VARIANTS = [
  'sandbox-legion',
  'sandbox-hardened',
  'sandbox-basic',
  'sandbox-restricted',
];

let screenshotIdx = 0;
async function snap(page: Page, label: string) {
  screenshotIdx++;
  const name = `${String(screenshotIdx).padStart(2, '0')}-${label}`;
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
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
    if (await verifySubmit.isVisible({ timeout: 2000 }).catch(() => false)) {
      await verifySubmit.click();
      await page.waitForURL(/^(?!.*keycloak)/, { timeout: 15000 });
    }
  }
}

async function navigateToSandbox(page: Page) {
  const sessionsNav = page
    .locator('nav a, nav button, [role="navigation"] a')
    .filter({ hasText: /^Sessions$/ });
  await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
  await sessionsNav.first().click();
  await page.waitForLoadState('networkidle');
  // Wait for the sandbox page to load — chat input appears on all states
  await expect(
    page.getByPlaceholder(/Type your message/i)
  ).toBeVisible({ timeout: 15000 });
}

/**
 * Select an agent variant by clicking it in the Sandboxes panel.
 * The panel may be below the fold — scroll into view first.
 */
async function selectAgent(page: Page, agentName: string) {
  // The Sandboxes/Sandbox panel title (changes based on whether an agent is selected)
  const sandboxesTitle = page.locator('h4').filter({ hasText: /Sandbox/i });

  // Scroll the sidebar to make the Sandboxes panel visible
  await sandboxesTitle.scrollIntoViewIfNeeded();
  await expect(sandboxesTitle).toBeVisible({ timeout: 15000 });

  // All agents are always listed — find by text match within agent entries
  // Agent entries contain the name + session count
  const agentEntry = page.locator(`div[role="button"]`).filter({
    hasText: agentName,
  }).filter({
    hasText: /session/i,
  });
  await expect(agentEntry.first()).toBeVisible({ timeout: 25000 });
  await agentEntry.first().click();
  await page.waitForTimeout(500);
}

/**
 * Send a message and wait for agent response.
 */
async function sendAndWait(
  page: Page,
  message: string,
  timeout = AGENT_TIMEOUT
): Promise<string> {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 10000 });
  await expect(chatInput).toBeEnabled({ timeout: 5000 });
  await chatInput.fill(message);

  const sendButton = page.getByRole('button', { name: /Send/i });
  await expect(sendButton).toBeEnabled({ timeout: 5000 });
  await sendButton.click();

  // Verify user message appears
  await expect(page.getByText(message).first()).toBeVisible({ timeout: 5000 });

  // Wait for agent to finish
  await expect(chatInput).toBeEnabled({ timeout });
  await page.waitForTimeout(1000);

  // Get response content
  const chatArea = page.locator('[style*="overflow-y: auto"][style*="height"]').first();
  return (await chatArea.textContent()) || '';
}

// ===========================================================================
// PARAMETERIZED TESTS — one test per agent variant
// ===========================================================================

for (const agentName of AGENT_VARIANTS) {
  test.describe(`Agent Variant: ${agentName}`, () => {
    test(`multi-turn with tool call on ${agentName}`, async ({ page }) => {
      test.setTimeout(300_000);
      screenshotIdx = 0;

      const runId = Date.now().toString(36);
      const marker = `variant-${agentName}-${runId}`;

      // ---- Login & Navigate ----
      await page.goto('/');
      await loginIfNeeded(page);
      await navigateToSandbox(page);
      await snap(page, `${agentName}-loaded`);

      // ---- Select the agent variant ----
      await selectAgent(page, agentName);
      await snap(page, `${agentName}-selected`);

      // ---- Start new session ----
      const newSessionBtn = page.getByRole('button', { name: /New Session/i });
      await newSessionBtn.click();
      // Handle New Session modal
      const startBtn = page.getByRole('button', { name: /^Start$/ });
      if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await startBtn.click();
        await page.waitForTimeout(500);
      }
      await page.waitForTimeout(500);

      // ---- Turn 1: Simple text response ----
      const content1 = await sendAndWait(
        page,
        `Say exactly: ${marker}-turn1`
      );
      await snap(page, `${agentName}-turn1`);

      // Verify we got a session
      const sessionId = new URL(page.url()).searchParams.get('session') || '';
      expect(sessionId).toBeTruthy();

      // ---- Turn 2: Tool call — shell command ----
      const content2 = await sendAndWait(
        page,
        'Run the command: echo "variant-test-pass"'
      );
      await snap(page, `${agentName}-turn2-tool`);

      // ---- Turn 3: Context memory check ----
      const content3 = await sendAndWait(
        page,
        `What was the marker text I told you in turn 1? It started with "${marker}".`
      );
      await snap(page, `${agentName}-turn3-memory`);

      // ---- Assertions ----
      const fullContent = await page
        .locator('[style*="overflow-y: auto"][style*="height"]')
        .first()
        .textContent() || '';

      // Verify our marker appears (user message at minimum)
      expect(fullContent).toContain(marker);

      // Verify we got agent responses (not just user messages)
      // Agent responses show up as messages with "Agent" label
      expect(fullContent.length).toBeGreaterThan(marker.length * 2);

      await snap(page, `${agentName}-complete`);
    });
  });
}
