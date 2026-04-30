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
import { loginIfNeeded } from './helpers/auth';

test.describe('Agent Catalog Page @extended', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display agent catalog page with title', async ({ page }) => {
    // Verify the page title is visible
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible();
  });

  test('should show agents or empty state after loading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
      timeout: 15000,
    });
    // Page loaded via beforeEach — table or empty state must be visible
    await expect(
      page.getByRole('grid').or(page.getByText(/No agents found/i).first())
    ).toBeVisible({ timeout: 15000 });
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

test.describe('Agent Catalog - With Deployed Agents @extended', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display agents table when agents are deployed', async ({ page }) => {
    // First ensure the page has loaded by checking for the heading
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
      timeout: 15000,
    });

    // Wait for either the table or the empty state message
    const table = page.getByRole('grid');
    const emptyState = page.getByText(/No agents found/i).first();

    await expect(table.or(emptyState)).toBeVisible({ timeout: 30000 });
  });

  test('should list weather-service agent if deployed', async ({ page }) => {
    // Wait for page content to render (API already called in beforeEach)
    await expect(
      page.getByRole('grid').or(page.getByText(/No agents found/i).first())
    ).toBeVisible({ timeout: 15000 });

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
    const table = page.getByRole('grid');
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

    // Find any agent link in the table (scoped to the table to avoid nav links)
    const table = page.getByRole('grid');
    if (!(await table.isVisible())) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No agents table visible to test navigation',
      });
      return;
    }

    const agentLink = table.getByRole('link').first();

    if ((await agentLink.count()) === 0) {
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
      await expect(page).toHaveURL(/\/agents\//, { timeout: 10000 });
    }
  });
});

test.describe('Agent Catalog - API Integration @extended', () => {
  test('should call backend API when loading agents', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Use waitForResponse to reliably detect the API call
    const responsePromise = page.waitForResponse(
      (response) => response.url().includes('/api/v1/agents'),
      { timeout: 30000 }
    );

    await page.locator('nav a', { hasText: 'Agents' }).first().click();

    const response = await responsePromise;

    // Verify API was called and returned a valid response
    expect(response.status()).toBeLessThan(500);
  });

  test('should handle API error gracefully', async ({ page }) => {
    // Set up the error mock BEFORE navigating
    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');

    // Component shows "Error loading agents" EmptyState on query failure
    await expect(
      page.getByText(/Error loading agents/i).first()
    ).toBeVisible({ timeout: 15000 });
  });

  test('should handle empty agent list', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Mock an empty response
    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');

    // Verify empty state is shown (use .first() to avoid strict mode violation with multiple matches)
    await expect(page.getByText(/No agents found/i).first()).toBeVisible({
      timeout: 10000,
    });
  });
});
