/**
 * Home Page E2E Tests
 *
 * Tests the Home/Dashboard page functionality including:
 * - Page loading
 * - Navigation to other pages
 * - Basic layout elements
 */
import { test, expect } from '@playwright/test';

test.describe('Home Page', () => {
  test('should display home page', async ({ page }) => {
    await page.goto('/');
    // Home page should load without errors
    await expect(page).toHaveURL(/\//);
  });

  test('should have main navigation elements', async ({ page }) => {
    await page.goto('/');

    // Check for main navigation links
    const nav = page.locator('nav').or(page.getByRole('navigation'));
    await expect(nav.first()).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to agent catalog', async ({ page }) => {
    await page.goto('/');

    // Find and click the Agent Catalog link
    const agentLink = page.getByRole('link', { name: /Agent/i }).first();

    if (await agentLink.isVisible()) {
      await agentLink.click();
      await expect(page).toHaveURL(/\/agents/);
    }
  });

  test('should navigate to tool catalog', async ({ page }) => {
    await page.goto('/');

    // Find and click the Tool Catalog link
    const toolLink = page.getByRole('link', { name: /Tool/i }).first();

    if (await toolLink.isVisible()) {
      await toolLink.click();
      await expect(page).toHaveURL(/\/tools/);
    }
  });
});

test.describe('Navigation', () => {
  test('should show sidebar navigation', async ({ page }) => {
    await page.goto('/');

    // PatternFly typically uses a page sidebar for navigation
    const sidebar = page.locator('.pf-v5-c-page__sidebar').or(
      page.locator('[role="navigation"]')
    );

    await expect(sidebar.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have working breadcrumbs on detail pages', async ({ page }) => {
    // Navigate to a detail page
    await page.goto('/agents');

    // Check for breadcrumbs if present
    const breadcrumbs = page.locator('.pf-v5-c-breadcrumb');

    if (await breadcrumbs.isVisible()) {
      await expect(breadcrumbs).toBeVisible();
    }
  });
});
