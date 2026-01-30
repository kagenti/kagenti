/**
 * Tool Catalog E2E Tests
 *
 * Tests the Tool Catalog page functionality including:
 * - Page loading and rendering
 * - Tool listing
 * - Namespace selection
 * - Navigation to tool details
 */
import { test, expect } from '@playwright/test';

test.describe('Tool Catalog Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/tools');
  });

  test('should display tool catalog page with title', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Tool Catalog/i })).toBeVisible();
  });

  test('should have namespace selector', async ({ page }) => {
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have import tool button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Import Tool/i })).toBeVisible();
  });

  test('should navigate to import page when clicking import button', async ({ page }) => {
    await page.getByRole('button', { name: /Import Tool/i }).click();
    await expect(page).toHaveURL(/\/tools\/import/);
  });
});

test.describe('Tool Catalog - With Deployed Tools', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/tools');
    await page.waitForLoadState('networkidle');
  });

  test('should display tools table when tools are deployed', async ({ page }) => {
    const table = page.getByRole('table');
    const emptyState = page.getByText(/No tools found/i);
    await expect(table.or(emptyState)).toBeVisible({ timeout: 30000 });
  });

  test('should list weather-tool if deployed', async ({ page }) => {
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/tools') && response.status() === 200,
      { timeout: 30000 }
    );

    const weatherToolRow = page.getByRole('row', { name: /weather-tool/i });

    if (await weatherToolRow.count() === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'weather-tool not deployed in this environment',
      });
      return;
    }

    await expect(weatherToolRow).toBeVisible();
  });
});

test.describe('Tool Catalog - API Integration', () => {
  test('should call backend API when loading tools', async ({ page }) => {
    let apiCalled = false;

    page.on('response', (response) => {
      if (response.url().includes('/api/v1/tools')) {
        apiCalled = true;
      }
    });

    await page.goto('/tools');
    await page.waitForLoadState('networkidle');

    expect(apiCalled).toBe(true);
  });

  test('should handle API error gracefully', async ({ page }) => {
    await page.route('**/api/v1/tools**', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/tools');

    await expect(page.getByText(/Error loading tools/i)).toBeVisible({
      timeout: 10000,
    });
  });

  test('should handle empty tool list', async ({ page }) => {
    await page.route('**/api/v1/tools**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    await page.goto('/tools');

    await expect(page.getByText(/No tools found/i)).toBeVisible({
      timeout: 10000,
    });
  });
});
