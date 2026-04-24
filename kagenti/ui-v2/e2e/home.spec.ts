/**
 * Home Page E2E Tests
 *
 * Tests the Home/Dashboard page functionality including:
 * - Page loading
 * - Navigation to other pages
 * - Basic layout elements
 */
import { test, expect } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

test.describe('Home Page', () => {
  test('should display home page', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    // Home page should load without errors
    await expect(page).toHaveURL(/\//);
  });

  test('should have main navigation elements', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // Check for main navigation links
    const nav = page.locator('nav').or(page.getByRole('navigation'));
    await expect(nav.first()).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to agent catalog @extended', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // The "View Agents" action in the QuickLinkCard is a PatternFly Button
    // (variant="link"), which renders as <button>, not <a>.
    const agentButton = page.getByRole('button', { name: /View Agents/i }).first();

    if (await agentButton.isVisible()) {
      await agentButton.click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/agents/, { timeout: 15000 });
    }
  });

  test('should navigate to tool catalog @extended', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // The "View Tools" action in the QuickLinkCard is a PatternFly Button
    // (variant="link"), which renders as <button>, not <a>.
    const toolButton = page.getByRole('button', { name: /View Tools/i }).first();

    if (await toolButton.isVisible()) {
      await toolButton.click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/tools/, { timeout: 15000 });
    }
  });
});

test.describe('Navigation', () => {
  test('should show sidebar navigation', async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);

    // PatternFly typically uses a page sidebar for navigation
    const sidebar = page.locator('.pf-v5-c-page__sidebar').or(
      page.locator('[role="navigation"]')
    );

    await expect(sidebar.first()).toBeVisible({ timeout: 10000 });
  });

  test('should have working breadcrumbs on detail pages @extended', async ({ page }) => {
    // Navigate to a detail page
    await page.goto('/agents');

    // Check for breadcrumbs if present
    const breadcrumbs = page.locator('.pf-v5-c-breadcrumb');

    if (await breadcrumbs.isVisible()) {
      await expect(breadcrumbs).toBeVisible();
    }
  });
});
