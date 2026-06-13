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
import { loginIfNeeded } from './helpers/auth';

test.describe('Tool Catalog Page @extended', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Tools' }).first().click();
    await page.waitForLoadState('networkidle');
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

test.describe('Tool Catalog - With Deployed Tools @extended', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Tools' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display tools table when tools are deployed', async ({ page }) => {
    // Page loaded via beforeEach — table or empty state must be visible
    const table = page.getByRole('grid');
    const emptyState = page.getByText(/No tools found/i).first();
    await expect(table.or(emptyState)).toBeVisible({ timeout: 15000 });
  });

  test('should list weather-tool if deployed', async ({ page }) => {
    // Wait for page to fully render (API called during beforeEach navigation)
    await expect(
      page.getByRole('grid').or(page.getByText(/No tools found/i).first())
    ).toBeVisible({ timeout: 15000 });

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

test.describe('Tool Catalog - API Integration @extended', () => {
  test('should call backend API when loading tools', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    const responsePromise = page.waitForResponse(
      (response) => response.url().includes('/api/v1/tools'),
      { timeout: 30000 }
    );

    await page.locator('nav a', { hasText: 'Tools' }).first().click();

    const response = await responsePromise;
    expect(response.url()).toContain('/api/v1/tools');
  });

  test('should handle API error gracefully', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.route('**/api/v1/tools**', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.locator('nav a', { hasText: 'Tools' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByText(/Error loading tools|error|failed/i).first()).toBeVisible({
      timeout: 10000,
    });
  });

  test('should handle empty tool list', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.route('**/api/v1/tools**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    await page.locator('nav a', { hasText: 'Tools' }).first().click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByText(/No tools found/i).first()).toBeVisible({
      timeout: 10000,
    });
  });
});
