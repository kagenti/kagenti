/**
 * Integrations Page E2E Tests
 *
 * Tests the Integrations page functionality including:
 * - Page loading and rendering
 * - Tab navigation (Repositories, Webhooks, Schedules, Alerts)
 * - Namespace selection
 * - Table display with mock data
 * - Empty state handling
 * - Error handling
 * - Delete modal interaction
 *
 * All API calls are mocked — no cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

const MOCK_INTEGRATION = {
  name: 'kagenti-main',
  namespace: 'team1',
  repository: {
    url: 'https://github.com/kagenti/kagenti',
    provider: 'github',
    branch: 'main',
  },
  agents: [{ name: 'tdd-agent', namespace: 'team1' }],
  webhooks: [{ name: 'pr-events', events: ['pull_request'] }],
  schedules: [
    { name: 'nightly-ci', cron: '0 2 * * *', skill: 'tdd:ci', agent: 'tdd-agent' },
  ],
  alerts: [],
  status: 'Connected',
  createdAt: '2026-03-01T00:00:00Z',
};

const MOCK_INTEGRATIONS_RESPONSE = { items: [MOCK_INTEGRATION] };
const EMPTY_INTEGRATIONS_RESPONSE = { items: [] };

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
test.describe('Integrations Page - Structure', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/integrations');
  });

  test('should display page with Integrations title', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Integrations/i })).toBeVisible();
  });

  test('should have namespace selector', async ({ page }) => {
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have Add Integration button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Add Integration/i })).toBeVisible();
  });

  test('should show Repositories tab by default', async ({ page }) => {
    const repositoriesTab = page.getByRole('tab', { name: /Repositories/i });
    await expect(repositoriesTab).toBeVisible({ timeout: 10000 });
    await expect(repositoriesTab).toHaveAttribute('aria-selected', 'true');
  });

  test('should show all four tabs', async ({ page }) => {
    await expect(page.getByRole('tab', { name: /Repositories/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('tab', { name: /Webhooks/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Schedules/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Alerts/i })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 2: Navigation
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    // Mock agents and tools APIs for the HomePage (navigation starts at /)
    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });
    await page.route('**/api/v1/tools**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });
  });

  test('should be accessible from sidebar navigation', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Click the Integrations link in the sidebar navigation
    const navLink = page.locator('nav').getByText('Integrations', { exact: true });
    await expect(navLink).toBeVisible({ timeout: 10000 });
    await navLink.click();

    await expect(page).toHaveURL(/\/integrations/);
    await expect(page.getByRole('heading', { name: /Integrations/i })).toBeVisible();
  });

  test('should highlight Integrations in sidebar when active', async ({ page }) => {
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');

    // PatternFly NavItem gets the pf-m-current class when active
    const navItem = page.locator('.pf-v5-c-nav__link.pf-m-current, .pf-m-current').filter({
      hasText: /Integrations/i,
    });

    await expect(navItem.first()).toBeVisible({ timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Group 3: Empty State (mock API returning empty list)
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Empty State', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(EMPTY_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');
  });

  test('should show empty state when no integrations exist', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: /No integrations found/i })
    ).toBeVisible({ timeout: 10000 });
  });

  test('should show Add Integration button in empty state', async ({ page }) => {
    // The empty state has its own "Add Integration" button
    await expect(
      page.getByRole('heading', { name: /No integrations found/i })
    ).toBeVisible({ timeout: 10000 });

    // There should be at least two "Add Integration" buttons:
    // one in the toolbar and one in the empty state
    const buttons = page.getByRole('button', { name: /Add Integration/i });
    await expect(buttons.first()).toBeVisible();
    const count = await buttons.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// Group 4: Populated Table (mock API returning data)
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Populated Table', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');
  });

  test('should display integration in table', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // Verify the integration name appears in the table
    await expect(page.getByText('kagenti-main')).toBeVisible();
  });

  test('should show repository URL', async ({ page }) => {
    // The component strips the protocol, so look for the domain/path
    await expect(page.getByText('github.com/kagenti/kagenti')).toBeVisible({
      timeout: 10000,
    });
  });

  test('should show provider label', async ({ page }) => {
    // The provider is rendered as a Label component with the provider name
    await expect(page.getByText('github', { exact: true })).toBeVisible({
      timeout: 10000,
    });
  });

  test('should show agent chips', async ({ page }) => {
    // The agent name is rendered as a Label (chip)
    await expect(page.getByText('tdd-agent')).toBeVisible({ timeout: 10000 });
  });

  test('should show Connected status badge', async ({ page }) => {
    // Status is rendered as a PatternFly Label
    const statusBadge = page.locator('.pf-v5-c-label').filter({
      hasText: /Connected/,
    });
    await expect(statusBadge.first()).toBeVisible({ timeout: 10000 });
  });

  test('should show webhook and schedule counts', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // The webhook and schedule columns show the count (length of arrays)
    // Our mock has 1 webhook and 1 schedule
    const row = page.getByRole('row', { name: /kagenti-main/i });
    await expect(row).toBeVisible();

    // The cells with dataLabel "Webhooks" and "Schedules" contain "1"
    const webhookCell = row.locator('[data-label="Webhooks"]');
    const scheduleCell = row.locator('[data-label="Schedules"]');

    await expect(webhookCell).toHaveText('1');
    await expect(scheduleCell).toHaveText('1');
  });
});

// ---------------------------------------------------------------------------
// Group 5: Tab Switching
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Tab Switching', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');
  });

  test('should switch to Webhooks tab', async ({ page }) => {
    const webhooksTab = page.getByRole('tab', { name: /Webhooks/i });
    await expect(webhooksTab).toBeVisible({ timeout: 10000 });
    await webhooksTab.click();

    await expect(webhooksTab).toHaveAttribute('aria-selected', 'true');
    // Webhooks tab shows a placeholder empty state
    await expect(page.getByText(/Webhook configuration will be available/i)).toBeVisible();
  });

  test('should switch to Schedules tab', async ({ page }) => {
    const schedulesTab = page.getByRole('tab', { name: /Schedules/i });
    await expect(schedulesTab).toBeVisible({ timeout: 10000 });
    await schedulesTab.click();

    await expect(schedulesTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText(/Schedule configuration will be available/i)).toBeVisible();
  });

  test('should switch to Alerts tab', async ({ page }) => {
    const alertsTab = page.getByRole('tab', { name: /Alerts/i });
    await expect(alertsTab).toBeVisible({ timeout: 10000 });
    await alertsTab.click();

    await expect(alertsTab).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText(/Alert routing configuration will be available/i)).toBeVisible();
  });

  test('should show tab badge counts when integrations have configs', async ({ page }) => {
    // With our mock data: 1 webhook, 1 schedule, 0 alerts
    // The tab titles include counts when > 0: "Webhooks (1)", "Schedules (1)"
    await expect(page.getByRole('tab', { name: /Repositories \(1\)/i })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByRole('tab', { name: /Webhooks \(1\)/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Schedules \(1\)/i })).toBeVisible();
    // Alerts count is 0, so no badge
    await expect(page.getByRole('tab', { name: /^Alerts$/i })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 6: Error Handling
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Error Handling', () => {
  test('should show error state when API fails', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/integrations');

    await expect(page.getByText(/Error loading integrations/i)).toBeVisible({
      timeout: 10000,
    });
  });

  test('should call integrations API on load', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });

    let apiCalled = false;

    page.on('response', (response) => {
      if (response.url().includes('/api/v1/integrations')) {
        apiCalled = true;
      }
    });

    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');

    expect(apiCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Group 7: Delete Modal
// ---------------------------------------------------------------------------
test.describe('Integrations Page - Delete Modal', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/integrations**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(MOCK_INTEGRATIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/integrations');
    await page.waitForLoadState('networkidle');
  });

  test('should open delete modal from actions menu', async ({ page }) => {
    // Wait for the table to render
    await expect(page.getByRole('grid')).toBeVisible({ timeout: 10000 });

    // Click the actions menu (kebab) for the integration row
    const actionsToggle = page.getByRole('button', { name: /Actions menu/i });
    await expect(actionsToggle.first()).toBeVisible();
    await actionsToggle.first().click();

    // Click "Delete integration" in the dropdown
    await page.getByRole('menuitem', { name: /Delete integration/i }).click();

    // Verify the delete modal is visible
    await expect(page.getByText(/Delete integration\?/i)).toBeVisible();
    await expect(page.getByText(/will be permanently deleted/i)).toBeVisible();
  });

  test('should require name confirmation to delete', async ({ page }) => {
    await expect(page.getByRole('grid')).toBeVisible({ timeout: 10000 });

    // Open the actions menu and click delete
    const actionsToggle = page.getByRole('button', { name: /Actions menu/i });
    await actionsToggle.first().click();
    await page.getByRole('menuitem', { name: /Delete integration/i }).click();

    // The Delete button should be disabled until the correct name is typed
    const deleteButton = page.getByRole('dialog').getByRole('button', { name: /^Delete$/i });
    await expect(deleteButton).toBeDisabled();

    // Type the wrong name
    const confirmInput = page.getByRole('dialog').locator('#delete-confirm-input');
    await confirmInput.fill('wrong-name');
    await expect(deleteButton).toBeDisabled();

    // Type the correct name
    await confirmInput.fill('kagenti-main');
    await expect(deleteButton).toBeEnabled();
  });

  test('should close modal on cancel', async ({ page }) => {
    await expect(page.getByRole('grid')).toBeVisible({ timeout: 10000 });

    // Open the delete modal
    const actionsToggle = page.getByRole('button', { name: /Actions menu/i });
    await actionsToggle.first().click();
    await page.getByRole('menuitem', { name: /Delete integration/i }).click();

    // Verify modal is open
    await expect(page.getByText(/Delete integration\?/i)).toBeVisible();

    // Click Cancel
    const cancelButton = page.getByRole('dialog').getByRole('button', { name: /Cancel/i });
    await cancelButton.click();

    // Verify modal is closed
    await expect(page.getByText(/Delete integration\?/i)).not.toBeVisible();
  });
});
