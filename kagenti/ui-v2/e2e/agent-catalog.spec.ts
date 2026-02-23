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
import { loginIfNeeded } from './auth';

test.describe('Agent Catalog Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display agent catalog page with title', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible();
  });

  test('should show agent list after loading', async ({ page }) => {
    // PatternFly renders tables as grid role
    const grid = page.getByRole('grid');
    const emptyState = page.getByRole('heading', { name: /No agents found/i });

    await expect(grid.or(emptyState)).toBeVisible({ timeout: 30000 });
  });

  test('should have namespace selector', async ({ page }) => {
    const namespaceSelector = page.locator('[aria-label="Select namespace"]').or(
      page.getByRole('button', { name: /team1/i })
    );
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have import agent button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Import Agent/i })).toBeVisible();
  });

  test('should navigate to import page when clicking import button', async ({ page }) => {
    await page.getByRole('button', { name: /Import Agent/i }).click();
    await expect(page).toHaveURL(/\/agents\/import/);
  });
});

test.describe('Agent Catalog - With Deployed Agents', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display agents grid when agents are deployed', async ({ page }) => {
    const grid = page.getByRole('grid');
    const emptyState = page.getByRole('heading', { name: /No agents found/i });
    await expect(grid.or(emptyState)).toBeVisible({ timeout: 30000 });
  });

  test('should list weather-service agent if deployed', async ({ page }) => {
    const weatherAgent = page.getByRole('button', { name: 'weather-service' });

    if (await weatherAgent.count() === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'weather-service not deployed in this environment',
      });
      return;
    }

    await expect(weatherAgent).toBeVisible();
  });

  test('should show agent status badge', async ({ page }) => {
    // Look for status labels (Ready, Running, Progressing, etc.)
    const statusBadge = page.locator('.pf-v5-c-label').filter({
      hasText: /Ready|Running|Progressing|Pending/i,
    });

    const grid = page.getByRole('grid');
    if (await grid.isVisible()) {
      const rows = page.getByRole('row');
      const rowCount = await rows.count();

      if (rowCount > 1) {
        await expect(statusBadge.first()).toBeVisible({ timeout: 10000 });
      }
    }
  });

  test('should navigate to agent detail page when clicking agent name', async ({ page }) => {
    // Find agent button in the grid (PatternFly renders agent names as buttons)
    const weatherAgent = page.getByRole('button', { name: 'weather-service' });

    if (await weatherAgent.count() === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'No agents deployed to test navigation',
      });
      return;
    }

    await weatherAgent.click();
    await expect(page).toHaveURL(/\/agents\/team1\/weather-service/, { timeout: 10000 });
  });
});

test.describe('Agent Catalog - API Integration', () => {
  test('should call backend API when loading agents', async ({ page }) => {
    let apiCalled = false;

    page.on('response', (response) => {
      if (response.url().includes('/api/v1/agents')) {
        apiCalled = true;
      }
    });

    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');

    // Wait a moment for response events to fire
    await page.waitForTimeout(1000);
    expect(apiCalled).toBe(true);
  });

  test('should handle API error gracefully', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.locator('nav a', { hasText: 'Agents' }).first().click();

    // Wait for error message or empty state
    await expect(
      page.getByText(/error/i).first()
        .or(page.getByRole('heading', { name: /No agents found/i }))
    ).toBeVisible({ timeout: 10000 });
  });

  test('should handle empty agent list', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    await page.route('**/api/v1/agents**', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ items: [] }),
        contentType: 'application/json',
      });
    });

    await page.locator('nav a', { hasText: 'Agents' }).first().click();

    await expect(page.getByRole('heading', { name: /No agents found/i })).toBeVisible({
      timeout: 10000,
    });
  });
});
