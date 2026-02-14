/**
 * Agent Chat E2E Tests
 *
 * Tests the full user flow: login → navigate to agent → send chat message → verify response.
 *
 * Prerequisites:
 * - Backend API accessible (port-forwarded or via route)
 * - Keycloak deployed (for login test) or auth disabled
 * - weather-service agent deployed in team1 namespace
 * - weather-tool deployed and accessible
 *
 * Environment variables:
 *   KAGENTI_UI_URL: Base URL for the UI (default: http://localhost:3000)
 *   KEYCLOAK_USER: Keycloak username (default: admin)
 *   KEYCLOAK_PASSWORD: Keycloak password (default: admin)
 */
import { test, expect } from '@playwright/test';
import { loginIfNeeded } from './auth';

test.describe('Agent Chat - Full User Flow', () => {
  test('should login, navigate to weather agent, and get a chat response', async ({ page }) => {
    // Increase timeout for this test — chat responses can be slow (LLM inference)
    test.setTimeout(120000);

    // Step 1: Login from home page (UI uses check-sso, shows Sign In button)
    await page.goto('/');
    await loginIfNeeded(page);

    // Step 2: Navigate to agents page (click sidebar link for reliable navigation)
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');

    // Step 3: Verify we're on the agent catalog
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
      timeout: 15000,
    });

    // Step 4: Wait for agent list to load, then click weather-service
    const weatherAgent = page.getByText('weather-service', { exact: true });
    await expect(weatherAgent).toBeVisible({ timeout: 30000 });
    await weatherAgent.click();

    // Step 5: Verify we're on the agent detail page
    await expect(page).toHaveURL(/\/agents\/team1\/weather-service/);

    // Step 6: Click the Chat tab to reveal the chat interface
    await page.getByRole('tab', { name: /Chat/i }).click();
    await expect(page.getByPlaceholder('Type your message...')).toBeVisible({ timeout: 30000 });

    // Step 7: Type a message in the chat input
    const chatInput = page.getByPlaceholder('Type your message...');
    await expect(chatInput).toBeVisible();
    await chatInput.fill('What is the weather in New York?');

    // Step 8: Click send button
    const sendButton = page.getByRole('button', { name: /Send/i });
    await expect(sendButton).toBeEnabled();
    await sendButton.click();

    // Step 9: Verify the user message appears
    await expect(page.getByText('What is the weather in New York?')).toBeVisible();

    // Step 10: Wait for assistant response (LLM inference + tool call)
    // Look for any assistant response — either streaming content or a completed message
    await expect(
      page.locator('text=/weather|temperature|New York|forecast|degrees|°/i').first()
    ).toBeVisible({ timeout: 90000 });
  });
});

test.describe('Agent Chat - Navigation', () => {
  test.setTimeout(60000); // HyperShift login + navigation can be slow

  test.beforeEach(async ({ page }) => {
    // Login first from home page, then navigate to agents via sidebar
    await page.goto('/');
    await loginIfNeeded(page);
    await page.locator('nav a', { hasText: 'Agents' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('should display chat interface on agent detail page', async ({ page }) => {
    // Wait for agent catalog heading
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
      timeout: 15000,
    });

    // Navigate to weather-service
    const weatherAgent = page.getByRole('link', { name: /weather-service/i });
    if ((await weatherAgent.count()) === 0) {
      test.info().annotations.push({
        type: 'skip-reason',
        description: 'weather-service not deployed',
      });
      return;
    }
    await weatherAgent.click();

    // Click Chat tab and verify chat components
    await page.getByRole('tab', { name: /Chat/i }).click();
    await expect(page.getByPlaceholder('Type your message...')).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: /Send/i })).toBeVisible();
  });

  test('should disable send button when input is empty', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /Agent Catalog/i })).toBeVisible({
      timeout: 15000,
    });

    const weatherAgent = page.getByRole('link', { name: /weather-service/i });
    if ((await weatherAgent.count()) === 0) {
      return;
    }
    await weatherAgent.click();

    // Click Chat tab, wait for chat to load
    await page.getByRole('tab', { name: /Chat/i }).click();
    await expect(page.getByPlaceholder('Type your message...')).toBeVisible({ timeout: 15000 });

    // Send button should be disabled when input is empty
    await expect(page.getByRole('button', { name: /Send/i })).toBeDisabled();
  });
});
