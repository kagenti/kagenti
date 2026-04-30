/**
 * Sandbox Agent Import Wizard — Walkthrough Tests
 *
 * Tests the full wizard flow for deploying sandbox agents with
 * different security configurations:
 *
 * 1. Basic agent — minimal config (name + repo, all defaults)
 * 2. Hardened agent — pod-per-session, custom Landlock, restricted proxy
 * 3. Enterprise agent — GitHub App mode, external DB, custom model
 *
 * Each test walks through all 6 wizard steps and verifies the
 * Review summary matches the configuration.
 *
 * Prerequisites:
 *   - Kagenti UI deployed with /sandbox/create route
 *   - Backend with POST /sandbox/{ns}/create endpoint
 *
 * Environment:
 *   KAGENTI_UI_URL: Base URL (default: auto-detect)
 *   KEYCLOAK_USER / KEYCLOAK_PASSWORD: Login credentials (default: admin/admin)
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

const SCREENSHOT_DIR = 'test-results/sandbox-create';

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
    if (
      await verifySubmit.isVisible({ timeout: 2000 }).catch(() => false)
    ) {
      await verifySubmit.click();
      await page.waitForURL(/^(?!.*keycloak)/, { timeout: 15000 });
    }
  }
}

/** Click the Next button and wait for step transition. */
async function clickNext(page: Page) {
  const nextBtn = page.getByRole('button', { name: /^Next$/i });
  await expect(nextBtn).toBeEnabled({ timeout: 5000 });
  await nextBtn.click();
  await page.waitForTimeout(300);
}

/** Navigate to the wizard page via SPA navigation (avoids Keycloak redirect losing path). */
async function navigateToWizard(page: Page) {
  // First navigate to sandbox page via sidebar
  const sessionsNav = page
    .locator('nav a, nav button, [role="navigation"] a')
    .filter({ hasText: /^Sessions$/ });
  await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
  await sessionsNav.first().click();
  await page.waitForLoadState('networkidle');

  // Then navigate to /sandbox/create using the browser's address bar
  // (SPA client-side navigation)
  await page.evaluate(() => {
    window.history.pushState({}, '', '/sandbox/create');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await page.waitForTimeout(1000);

  // If that didn't work (React Router may not listen to popstate),
  // try direct navigation now that we're already authenticated
  const heading = page.getByRole('heading', { name: /Create Sandbox Agent/i });
  if (!(await heading.isVisible({ timeout: 3000 }).catch(() => false))) {
    await page.goto('/sandbox/create');
    await page.waitForLoadState('networkidle');
  }

  await expect(heading).toBeVisible({ timeout: 15000 });
}

// ==========================================================================
// TEST 1: Basic Agent (minimal config, all defaults)
// ==========================================================================

test.describe('Import Wizard — Basic Agent', () => {
  test('walks through all steps with minimal config', async ({ page }) => {
    test.setTimeout(120000);
    screenshotIdx = 0;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);
    await snap(page, 'basic-step1-source');

    // Step 1: Source — fill required fields only
    await page.locator('#agent-name').fill('test-basic-agent');
    await page.locator('#repo-url').fill('https://github.com/kagenti/agent-examples');
    await snap(page, 'basic-step1-filled');

    // Verify Next is enabled (name + repo filled)
    await clickNext(page);
    await snap(page, 'basic-step2-security');

    // Step 2: Security — accept all defaults
    // Verify the combined container-hardening toggle is on by default
    await expect(page.locator('#secctx')).toBeChecked();
    await clickNext(page);
    await snap(page, 'basic-step3-identity');

    // Step 3: Identity — verify defaults (PAT mode + existing secret)
    const credMode = page.locator('#cred-mode');
    await expect(credMode).toBeVisible();

    // Existing secret should be the default for LLM key
    const llmKeySource = page.locator('#llm-key-source');
    await expect(llmKeySource).toBeVisible({ timeout: 5000 });

    // Secret name field should show default "openai-secret"
    await expect(page.locator('#llm-secret-name')).toHaveValue('openai-secret');
    await clickNext(page);
    await snap(page, 'basic-step4-persistence');

    // Step 4: Persistence — accept defaults (enabled)
    await expect(page.locator('#enable-persistence')).toBeChecked();
    await clickNext(page);
    await snap(page, 'basic-step5-observability');

    // Step 5: Observability — accept defaults
    await expect(page.locator('#otel-endpoint')).toHaveValue(
      'otel-collector.kagenti-system:8335'
    );
    await clickNext(page);
    await snap(page, 'basic-step6-budget');

    // Step 6: Budget — accept defaults
    await expect(page.locator('#max-iterations')).toHaveValue('100');
    await clickNext(page);
    await snap(page, 'basic-step7-review');

    // Step 7: Review — verify summary shows our values
    const review = page.locator('.pf-v5-c-card__body').first();
    await expect(review).toContainText('test-basic-agent');
    await expect(review).toContainText('kagenti/agent-examples');
    await expect(review).toContainText('main');
    await expect(review).toContainText('sandbox-legion');
    await expect(review).toContainText('llama-4-scout');
    await expect(review).toContainText('in-cluster');

    // Verify Deploy button exists
    const deployBtn = page.getByRole('button', { name: /Deploy Agent/i });
    await expect(deployBtn).toBeVisible();
    await snap(page, 'basic-review-verified');

    // Verify Back button works
    const backBtn = page.getByRole('button', { name: /^Back$/i });
    await backBtn.click();
    await page.waitForTimeout(300);
    // Should be on step 6 (Budget)
    await expect(page.locator('#max-iterations')).toBeVisible();
    await snap(page, 'basic-back-to-step6');
  });
});

// ==========================================================================
// TEST 2: Hardened Agent (max security)
// ==========================================================================

test.describe('Import Wizard — Hardened Agent', () => {
  test('configures pod-per-session isolation with custom security', async ({
    page,
  }) => {
    test.setTimeout(180000);
    screenshotIdx = 100;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Step 1: Source
    await page.locator('#agent-name').fill('secure-code-reviewer');
    await page.locator('#repo-url').fill('https://github.com/myorg/code-review-agent');
    await page.locator('#branch').clear();
    await page.locator('#branch').fill('release/v2');
    await page.locator('#context-dir').fill('/agents/reviewer');
    await page.locator('#variant').selectOption('sandbox-agent');
    await snap(page, 'hardened-step1-source');
    await clickNext(page);

    // Step 2: Security — change to pod-per-session, modify rules
    await page.locator('#isolation-mode').selectOption('pod-per-session');
    await snap(page, 'hardened-step2-isolation');

    // Enable Landlock filesystem sandbox
    // PatternFly <Switch> hides the <input> (opacity: 0), so use .check()
    // which handles hidden checkboxes, instead of .click() which requires visibility.
    const landlockSwitch = page.locator('#landlock');
    await landlockSwitch.check({ force: true });
    await expect(landlockSwitch).toBeChecked();

    // Enable network proxy and modify allowed domains
    const proxySwitch = page.locator('#proxy');
    await proxySwitch.check({ force: true });
    await expect(proxySwitch).toBeChecked();

    // Wait for proxy-domains field to appear (conditional on proxy being checked)
    const proxyField = page.locator('#proxy-domains');
    await expect(proxyField).toBeVisible({ timeout: 5000 });
    await proxyField.clear();
    await proxyField.fill('github.com, api.github.com');

    // Change workspace size
    await page.locator('#workspace-size').selectOption('10Gi');

    // Change TTL
    await page.locator('#session-ttl').selectOption('1d');

    await snap(page, 'hardened-step2-configured');
    await clickNext(page);

    // Step 3: Identity — keep PAT, switch to "paste new key" mode
    await page.locator('#llm-key-source').selectOption('new');
    await page.locator('#llm-key').fill('sk-test-hardened-key-123');
    await snap(page, 'hardened-step3-identity');
    await clickNext(page);

    // Step 4: Persistence — keep defaults
    await clickNext(page);

    // Step 5: Observability — change model
    await page.locator('#model').selectOption('mistral-small');
    await snap(page, 'hardened-step5-model');
    await clickNext(page);

    // Step 6: Budget — accept defaults
    await clickNext(page);

    // Step 7: Review — verify hardened config
    const review = page.locator('.pf-v5-c-card__body').first();
    await expect(review).toContainText('secure-code-reviewer');
    await expect(review).toContainText('code-review-agent');
    await expect(review).toContainText('sandbox-agent'); // variant
    await expect(review).toContainText('pod-per-session');
    await expect(review).toContainText('mistral-small');
    await snap(page, 'hardened-review-verified');
  });
});

// ==========================================================================
// TEST 3: Enterprise Agent (GitHub App + external DB)
// ==========================================================================

test.describe('Import Wizard — Enterprise Agent', () => {
  test('configures GitHub App credentials and external database', async ({
    page,
  }) => {
    test.setTimeout(120000);
    screenshotIdx = 200;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Step 1: Source
    await page.locator('#agent-name').fill('enterprise-deployer');
    await page.locator('#repo-url').fill('https://github.com/enterprise/deploy-agent');
    await snap(page, 'enterprise-step1');
    await clickNext(page);

    // Step 2: Security — defaults
    await clickNext(page);

    // Step 3: Identity — switch to GitHub App mode
    await page.locator('#cred-mode').selectOption('github-app');
    await snap(page, 'enterprise-step3-github-app');

    // Verify GitHub App info alert appears
    await expect(
      page.getByText(/GitHub App Setup/i)
    ).toBeVisible({ timeout: 5000 });

    // LLM key — switch to paste mode and fill
    await page.locator('#llm-key-source').selectOption('new');
    await page.locator('#llm-key').fill('sk-enterprise-key-456');
    await clickNext(page);

    // Step 4: Persistence — switch to external DB
    await page.locator('#db-source').selectOption('external');
    await snap(page, 'enterprise-step4-external-db');

    // Verify external DB URL field appears
    const externalDbField = page.locator('#external-db');
    await expect(externalDbField).toBeVisible({ timeout: 3000 });
    await externalDbField.fill('postgresql://user:pass@rds.example.com:5432/sessions');
    await snap(page, 'enterprise-step4-db-filled');
    await clickNext(page);

    // Step 5: Observability — use GPT-4o model
    await page.locator('#model').selectOption('gpt-4o');
    await clickNext(page);

    // Step 6: Budget — accept defaults
    await clickNext(page);

    // Step 7: Review — verify enterprise config
    const review = page.locator('.pf-v5-c-card__body').first();
    await expect(review).toContainText('enterprise-deployer');
    await expect(review).toContainText('GitHub App');
    await expect(review).toContainText('external');
    await expect(review).toContainText('gpt-4o'); // model ID shown in review
    await snap(page, 'enterprise-review-verified');
  });
});

// ==========================================================================
// TEST 4: Wizard Navigation (stepper clicks, cancel)
// ==========================================================================

test.describe('Import Wizard — Navigation', () => {
  test('stepper allows jumping to completed steps', async ({ page }) => {
    test.setTimeout(60000);
    screenshotIdx = 300;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Fill step 1 and advance to step 3
    await page.locator('#agent-name').fill('nav-test-agent');
    await page.locator('#repo-url').fill('https://github.com/test/repo');
    await clickNext(page); // → step 2
    await clickNext(page); // → step 3

    // Click step 1 in the progress stepper to go back
    const step1Stepper = page.locator('[id="step-0"]');
    await step1Stepper.click();
    await page.waitForTimeout(300);

    // Verify we're back on step 1 with values preserved
    await expect(page.locator('#agent-name')).toHaveValue('nav-test-agent');
    await expect(page.locator('#repo-url')).toHaveValue('https://github.com/test/repo');
    await snap(page, 'nav-back-to-step1');
  });

  test('cancel button navigates back to sandbox page', async ({ page }) => {
    test.setTimeout(60000);
    screenshotIdx = 310;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Click Cancel (Back button on step 1)
    const cancelBtn = page.getByRole('button', { name: /^Cancel$/i });
    await expect(cancelBtn).toBeVisible();
    await cancelBtn.click();
    await page.waitForLoadState('networkidle');

    // Should navigate to /sandbox
    await expect(
      page.getByRole('heading', { name: /sandbox-legion/i })
    ).toBeVisible({ timeout: 15000 });
    await snap(page, 'nav-cancel-to-sandbox');
  });

  test('next button disabled without required fields', async ({ page }) => {
    test.setTimeout(60000);
    screenshotIdx = 320;

    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToWizard(page);

    // Next should be disabled (no name or repo)
    const nextBtn = page.getByRole('button', { name: /^Next$/i });
    await expect(nextBtn).toBeDisabled();

    // Fill only name — still disabled
    await page.locator('#agent-name').fill('partial-agent');
    await expect(nextBtn).toBeDisabled();

    // Fill repo — now enabled
    await page.locator('#repo-url').fill('https://github.com/test/repo');
    await expect(nextBtn).toBeEnabled();
    await snap(page, 'nav-validation');
  });
});
