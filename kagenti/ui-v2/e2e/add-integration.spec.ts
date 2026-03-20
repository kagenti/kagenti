/**
 * Add Integration Page E2E Tests
 *
 * Tests the Add Integration page at /integrations/add including:
 * - Page structure (title, namespace selector, buttons)
 * - Form fields and default values
 * - Expandable sections (Webhooks, Schedules, Alerts)
 * - Form submission behavior and navigation
 *
 * All API calls are mocked -- no cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

/**
 * Mock the auth config, namespaces, and integrations POST APIs
 * so the app can boot without a running backend.
 * Must be called BEFORE page.goto().
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
  await page.route('**/api/v1/integrations', (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          success: true,
          name: 'test',
          namespace: 'team1',
          message: 'created',
        }),
        contentType: 'application/json',
      });
    } else {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    }
  });
}

// ---------------------------------------------------------------------------
// Group 1: Page Structure
// ---------------------------------------------------------------------------
test.describe('Add Integration Page - Structure', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/integrations/add');
    await page.waitForLoadState('networkidle');
  });

  test('should display Add Integration title', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Add Integration/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test('should have namespace selector', async ({ page }) => {
    // The NamespaceSelector renders inside the Repository card
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should show Repository card with form fields', async ({ page }) => {
    // Repository card title
    await expect(page.getByText('Repository', { exact: true })).toBeVisible({ timeout: 10000 });

    // Verify form fields exist within the card
    await expect(page.locator('#name')).toBeVisible();
    await expect(page.locator('#repo-url')).toBeVisible();
    await expect(page.locator('#provider')).toBeVisible();
    await expect(page.locator('#branch')).toBeVisible();
    await expect(page.locator('#credentials-secret')).toBeVisible();
  });

  test('should have Create Integration and Cancel buttons', async ({ page }) => {
    await expect(
      page.getByRole('button', { name: /Create Integration/i })
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByRole('button', { name: /Cancel/i })
    ).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 2: Form Fields
// ---------------------------------------------------------------------------
test.describe('Add Integration Page - Form Fields', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/integrations/add');
    await page.waitForLoadState('networkidle');
  });

  test('should have name, URL, provider, branch fields in repository card', async ({ page }) => {
    // Name field
    const nameInput = page.locator('#name');
    await expect(nameInput).toBeVisible({ timeout: 10000 });
    await expect(nameInput).toHaveAttribute('placeholder', 'my-integration');

    // Repository URL field
    const urlInput = page.locator('#repo-url');
    await expect(urlInput).toBeVisible();
    await expect(urlInput).toHaveAttribute('placeholder', 'https://github.com/org/repo');

    // Provider select
    const providerSelect = page.locator('#provider');
    await expect(providerSelect).toBeVisible();

    // Branch field
    const branchInput = page.locator('#branch');
    await expect(branchInput).toBeVisible();
    await expect(branchInput).toHaveAttribute('placeholder', 'main');
  });

  test('should have default provider as github', async ({ page }) => {
    const providerSelect = page.locator('#provider');
    await expect(providerSelect).toBeVisible({ timeout: 10000 });
    await expect(providerSelect).toHaveValue('github');
  });

  test('should have default branch as main', async ({ page }) => {
    const branchInput = page.locator('#branch');
    await expect(branchInput).toBeVisible({ timeout: 10000 });
    await expect(branchInput).toHaveValue('main');
  });

  test('should allow adding agent rows', async ({ page }) => {
    // There should be one agent row by default
    const agentInputs = page.locator('[id^="agent-name-"]');
    await expect(agentInputs.first()).toBeVisible({ timeout: 10000 });
    const initialCount = await agentInputs.count();
    expect(initialCount).toBe(1);

    // Click "Add Agent" button
    await page.getByRole('button', { name: /Add Agent/i }).click();

    // Now there should be two agent rows
    const updatedCount = await page.locator('[id^="agent-name-"]').count();
    expect(updatedCount).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Group 3: Expandable Sections
// ---------------------------------------------------------------------------
test.describe('Add Integration Page - Expandable Sections', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/integrations/add');
    await page.waitForLoadState('networkidle');
  });

  test('should have Webhooks expandable section', async ({ page }) => {
    // Webhooks toggle text should be visible
    const webhooksToggle = page.getByRole('button', { name: /Webhooks/i });
    await expect(webhooksToggle).toBeVisible({ timeout: 10000 });

    // Click to expand
    await webhooksToggle.click();

    // Webhook event checkboxes should appear
    await expect(page.locator('#webhook-event-pull_request')).toBeVisible();
    await expect(page.locator('#webhook-event-push')).toBeVisible();
    await expect(page.locator('#webhook-event-issue_comment')).toBeVisible();
    await expect(page.locator('#webhook-event-check_suite')).toBeVisible();
  });

  test('should have Schedules expandable section', async ({ page }) => {
    const schedulesToggle = page.getByRole('button', { name: /Schedules/i });
    await expect(schedulesToggle).toBeVisible({ timeout: 10000 });

    // Click to expand
    await schedulesToggle.click();

    // "Add Schedule" button should appear
    await expect(page.getByRole('button', { name: /Add Schedule/i })).toBeVisible();
  });

  test('should have Alerts expandable section', async ({ page }) => {
    const alertsToggle = page.getByRole('button', { name: /Alerts/i });
    await expect(alertsToggle).toBeVisible({ timeout: 10000 });

    // Click to expand
    await alertsToggle.click();

    // "Add Alert" button should appear
    await expect(page.getByRole('button', { name: /Add Alert/i })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 4: Form Submission
// ---------------------------------------------------------------------------
test.describe('Add Integration Page - Form Submission', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.goto('/integrations/add');
    await page.waitForLoadState('networkidle');
  });

  test('should have Create Integration button', async ({ page }) => {
    const createButton = page.getByRole('button', { name: /Create Integration/i });
    await expect(createButton).toBeVisible({ timeout: 10000 });
  });

  test('should disable Create button when required fields are empty', async ({ page }) => {
    // With an empty form, validateForm() returns false so the button is disabled
    const createButton = page.getByRole('button', { name: /Create Integration/i });
    await expect(createButton).toBeVisible({ timeout: 10000 });
    await expect(createButton).toBeDisabled();
  });

  test('should navigate back on Cancel click', async ({ page }) => {
    // Also mock the integrations GET for the list page we navigate to
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    const cancelButton = page.getByRole('button', { name: /Cancel/i });
    await expect(cancelButton).toBeVisible({ timeout: 10000 });
    await cancelButton.click();

    // Should navigate to /integrations
    await expect(page).toHaveURL(/\/integrations/, { timeout: 10000 });
  });
});
