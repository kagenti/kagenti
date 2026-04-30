/**
 * Trigger Management Page E2E Tests
 *
 * Tests the Triggers page functionality including:
 * - Page structure (title, namespace selector, tabs)
 * - Cron form fields and submission
 * - Webhook form fields and submission
 * - Alert form fields and submission
 * - Success and error alerts on form submission
 *
 * All API calls are mocked -- no cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

/**
 * Mock the auth config and namespaces APIs so the app can boot
 * without a running backend. Must be called BEFORE page.goto().
 */
async function mockBackendAPIs(page: Page) {
  await page.route('**/api/v1/auth/config', (route) => {
    route.fulfill({
      status: 200,
      body: JSON.stringify({ enabled: false }),
      contentType: 'application/json',
    });
  });
  await page.route('**/api/v1/namespaces**', (route) => {
    route.fulfill({
      status: 200,
      body: JSON.stringify({ namespaces: ['team1', 'team2'] }),
      contentType: 'application/json',
    });
  });
}

// ---------------------------------------------------------------------------
// Group 1: Page Structure
// ---------------------------------------------------------------------------
test.describe('Triggers Page - Page Structure', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');
  });

  test('should display page with Triggers title', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Triggers/i })).toBeVisible();
  });

  test('should have namespace selector', async ({ page }) => {
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should show all three tabs', async ({ page }) => {
    await expect(page.getByRole('tab', { name: /Cron/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('tab', { name: /Webhook/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Alert/i })).toBeVisible();
  });

  test('should show Cron tab selected by default', async ({ page }) => {
    const cronTab = page.getByRole('tab', { name: /Cron/i });
    await expect(cronTab).toBeVisible({ timeout: 10000 });
    await expect(cronTab).toHaveAttribute('aria-selected', 'true');
  });
});

// ---------------------------------------------------------------------------
// Group 2: Cron Form
// ---------------------------------------------------------------------------
test.describe('Triggers Page - Cron Form', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');
  });

  test('should show skill name field', async ({ page }) => {
    await expect(page.locator('#cron-skill')).toBeVisible({ timeout: 10000 });
  });

  test('should show schedule field with cron expression helper', async ({ page }) => {
    await expect(page.locator('#cron-schedule')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Cron expression')).toBeVisible();
  });

  test('should show Create Trigger button', async ({ page }) => {
    // The button is inside the Cron tab
    const createButton = page.getByRole('button', { name: /Create Trigger/i });
    await expect(createButton.first()).toBeVisible({ timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Group 3: Webhook Form
// ---------------------------------------------------------------------------
test.describe('Triggers Page - Webhook Form', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');
    // Switch to the Webhook tab
    const webhookTab = page.getByRole('tab', { name: /Webhook/i });
    await expect(webhookTab).toBeVisible({ timeout: 10000 });
    await webhookTab.click();
  });

  test('should switch to Webhook tab', async ({ page }) => {
    const webhookTab = page.getByRole('tab', { name: /Webhook/i });
    await expect(webhookTab).toHaveAttribute('aria-selected', 'true');
  });

  test('should show event type, repository, and branch fields', async ({ page }) => {
    await expect(page.locator('#webhook-event')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#webhook-repo')).toBeVisible();
    await expect(page.locator('#webhook-branch')).toBeVisible();
  });

  test('should show Create Trigger button', async ({ page }) => {
    const createButton = page.getByRole('button', { name: /Create Trigger/i });
    await expect(createButton.first()).toBeVisible({ timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Group 4: Alert Form
// ---------------------------------------------------------------------------
test.describe('Triggers Page - Alert Form', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');
    // Switch to the Alert tab
    const alertTab = page.getByRole('tab', { name: /Alert/i });
    await expect(alertTab).toBeVisible({ timeout: 10000 });
    await alertTab.click();
  });

  test('should switch to Alert tab', async ({ page }) => {
    const alertTab = page.getByRole('tab', { name: /Alert/i });
    await expect(alertTab).toHaveAttribute('aria-selected', 'true');
  });

  test('should show alert name and severity fields', async ({ page }) => {
    await expect(page.locator('#alert-name')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#alert-severity')).toBeVisible();
  });

  test('should show Create Trigger button', async ({ page }) => {
    const createButton = page.getByRole('button', { name: /Create Trigger/i });
    await expect(createButton.first()).toBeVisible({ timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Group 5: Form Submission
// ---------------------------------------------------------------------------
test.describe('Triggers Page - Form Submission', () => {
  test('should show success alert on successful cron trigger creation', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/trigger', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          sandbox_claim: 'sbx-cron-abc123',
          namespace: 'team1',
        }),
        contentType: 'application/json',
      });
    });
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');

    // Fill out the cron form
    await page.locator('#cron-skill').fill('tdd:ci');

    // Click create
    const createButton = page.getByRole('button', { name: /Create Trigger/i });
    await createButton.first().click();

    // Verify success alert
    await expect(page.getByText(/Trigger created successfully/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/sbx-cron-abc123/i)).toBeVisible();
  });

  test('should show error alert on failed trigger creation', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/trigger', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ detail: 'Cluster not available' }),
        contentType: 'application/json',
      });
    });
    await page.goto('/triggers');
    await page.waitForLoadState('networkidle');

    // Fill out the cron form
    await page.locator('#cron-skill').fill('tdd:ci');

    // Click create
    const createButton = page.getByRole('button', { name: /Create Trigger/i });
    await createButton.first().click();

    // Verify error alert
    await expect(page.getByText(/Failed to create trigger/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Cluster not available/i)).toBeVisible();
  });
});
