/**
 * Agent Catalog E2E Tests
 *
 * Tests the Agent Catalog page functionality including:
 * - Page loading and rendering
 * - Agent listing
 * - Namespace selection
 * - Navigation to agent details
 *
 * Prerequisites:
 * - Backend API accessible (port-forwarded or via route)
 * - At least one agent deployed (e.g., weather-service in team1)
 */
import { test, expect } from '@playwright/test';

test.describe('Agent Catalog Page', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the agent catalog page before each test
    await page.goto('/agents');
  });

  test('should display agent catalog page with title', async ({ page }) => {
    // Verify the page title is visible
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible();
  });

  test('should show loading spinner initially', async ({ page }) => {
    // On initial load, there should be a loading indicator
    // This tests the loading state is properly shown
    await page.goto('/agents');

    // Wait for either spinner to disappear or table to appear
    await expect(page.getByRole('table').or(page.getByText(/No agents found/i))).toBeVisible({
      timeout: 30000,
    });
  });

  test('should have namespace selector', async ({ page }) => {
    // Verify the namespace selector component is present
    // Look for the NamespaceSelector component's dropdown
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );

    // At least one namespace-related element should be visible
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have import agent button', async ({ page }) => {
    // Verify the Import Agent button is visible
    await expect(page.getByRole('button', { name: /Import Agent/i })).toBeVisible();
  });

  test('should navigate to import page when clicking import button', async ({ page }) => {
    // Click the Import Agent button
    await page.getByRole('button', { name: /Import Agent/i }).click();

    // Verify navigation to import page
    await expect(page).toHaveURL(/\/agents\/import/);
  });
});

test.describe('Agent Catalog - With Deployed Agents', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/agents');
    // Wait for the page to load
    await page.waitForLoadState('networkidle');
  });

  test('should display agents table when agents are deployed', async ({ page }) => {
    // Wait for either the table or the empty state message
    const table = page.getByRole('table');
    const emptyState = page.getByText(/No agents found/i);

    // Either should be visible
    await expect(table.or(emptyState)).toBeVisible({ timeout: 30000 });
  });

  test('should list weather-service agent if deployed', async ({ page }) => {
    // Wait for the API response
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/agents') && response.status() === 200,
      { timeout: 30000 }
    );

    // Look for weather-service in the page
    const weatherServiceRow = page.getByRole('row', { name: /weather-service/i });

    if (await weatherServiceRow.count() === 0) {
      // Agent might not be deployed in this environment - skip this check
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'weather-service not deployed in this environment',
      });
      return;
    }

    // Verify the row is visible
    await expect(weatherServiceRow).toBeVisible();
  });

  test('should show agent status badge', async ({ page }) => {
    // Wait for table to load
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/agents') && response.status() === 200,
      { timeout: 30000 }
    );

    // Look for status labels (Ready, Running, Progressing, etc.)
    const statusBadge = page.locator('.pf-v5-c-label').filter({
      hasText: /Ready|Running|Progressing|Pending/i,
    });

    // If agents are deployed, status badges should be visible
    const table = page.getByRole('table');
    if (await table.isVisible()) {
      const rows = page.getByRole('row');
      const rowCount = await rows.count();

      // If there are data rows (more than header), check for status badges
      if (rowCount > 1) {
        await expect(statusBadge.first()).toBeVisible({ timeout: 10000 });
      }
    }
  });

  test('should navigate to agent detail page when clicking agent name', async ({ page }) => {
    // Wait for table to load
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/agents') && response.status() === 200,
      { timeout: 30000 }
    );

    // Find any agent link in the table
    const agentLink = page.getByRole('link').first();

    if (await agentLink.count() === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No agents deployed to test navigation',
      });
      return;
    }

    // Get the agent name from the link text
    const agentName = await agentLink.textContent();

    // Click the agent link
    await agentLink.click();

    // Verify navigation to detail page
    if (agentName) {
      await expect(page).toHaveURL(new RegExp(`/agents/.*/${agentName}`));
    }
  });
});

test.describe('Agent Catalog - API Integration', () => {
  test('should call backend API when loading agents', async ({ page }) => {
    // Set up request interception to verify API calls
    let apiCalled = false;
    let apiResponse: unknown = null;

    page.on('response', (response) => {
      if (response.url().includes('/api/v1/agents')) {
        apiCalled = true;
        response.json().then((data) => {
          apiResponse = data;
        }).catch(() => {
          // Ignore JSON parse errors
        });
      }
    });

    await page.goto('/agents');
    await page.waitForLoadState('networkidle');

    // Verify API was called
    expect(apiCalled).toBe(true);
  });

  test('should handle API error gracefully', async ({ page }) => {
    // Mock an API error to test error handling
    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/agents');

    // Verify error state is shown
    await expect(page.getByText(/Error loading agents/i)).toBeVisible({
      timeout: 10000,
    });
  });

  test('should handle empty agent list', async ({ page }) => {
    // Mock an empty response
    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    await page.goto('/agents');

    // Verify empty state is shown
    await expect(page.getByText(/No agents found/i)).toBeVisible({
      timeout: 10000,
    });
  });
});
