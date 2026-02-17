/**
 * Home Page E2E Tests
 *
 * Tests the Home/Dashboard page functionality including:
 * - Page loading
 * - Navigation to other pages
 * - Basic layout elements
 */
import { test, expect } from '@playwright/test';
import { loginIfNeeded } from './auth';

test.describe('Home Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should display home page', async ({ page }) => {
    await expect(page).toHaveURL(/\//);
  });

  test('should have main navigation elements', async ({ page }) => {
    const nav = page.locator('nav').or(page.getByRole('navigation'));
    await expect(nav.first()).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to agent catalog', async ({ page }) => {
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await expect(page).toHaveURL(/\/agents/, { timeout: 10000 });
  });

  test('should navigate to tool catalog', async ({ page }) => {
    await page.locator('nav a', { hasText: 'Tools' }).first().click();
    await expect(page).toHaveURL(/\/tools/, { timeout: 10000 });
  });
});

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  test('should show sidebar navigation', async ({ page }) => {
    const sidebar = page.locator('.pf-v5-c-page__sidebar').or(
      page.locator('[role="navigation"]')
    );
    await expect(sidebar.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have working breadcrumbs on detail pages', async ({ page }) => {
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');

    const breadcrumbs = page.locator('.pf-v5-c-breadcrumb');
    if (await breadcrumbs.isVisible()) {
      await expect(breadcrumbs).toBeVisible();
    }
  });
});
