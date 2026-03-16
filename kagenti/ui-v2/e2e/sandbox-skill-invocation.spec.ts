/**
 * Sandbox Skill Invocation E2E Tests
 *
 * Tests that the frontend correctly parses /skill:name prefixes from user input
 * and sends them as a `skill` field in the streaming request body.
 *
 * Uses Playwright route interception to capture POST bodies — no real agent needed.
 * All API calls are mocked to avoid Keycloak redirect.
 */
import { test, expect, type Page, type Route } from '@playwright/test';

const MOCK_SKILLS = [
  {
    id: 'tdd:ci',
    name: 'TDD CI',
    description: 'TDD workflow against CI pipelines',
    examples: ['Analyze latest CI failures'],
    tags: ['ci', 'tdd'],
  },
  {
    id: 'rca:ci',
    name: 'RCA CI',
    description: 'Root cause analysis from CI logs',
    examples: ['Analyze CI failures for PR #758'],
    tags: ['ci', 'debugging'],
  },
];

/** Mock all API endpoints to bypass auth and provide agent data */
async function setupMocks(page: Page) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url();

    // Disable auth
    if (url.includes('/auth/config')) {
      await route.fulfill({ json: { enabled: false } });
      return;
    }

    // Agent list
    if (url.includes('/sandbox/') && url.includes('/agents')) {
      await route.fulfill({
        json: [{
          name: 'sandbox-legion',
          namespace: 'team1',
          status: 'ready',
          replicas: '1/1',
          session_count: 0,
          active_sessions: 0,
          image: 'sandbox-agent:latest',
          created: '2026-03-01T00:00:00Z',
        }],
      });
      return;
    }

    // Agent card with skills (handles both /chat/ and /sandbox/ endpoints)
    if (url.includes('/agent-card')) {
      await route.fulfill({
        json: {
          name: 'sandbox-legion',
          description: 'A sandboxed coding assistant',
          version: '0.1.0',
          url: 'http://sandbox-legion:8000',
          streaming: true,
          skills: MOCK_SKILLS,
        },
      });
      return;
    }

    // Sessions list
    if (url.includes('/sessions')) {
      await route.fulfill({ json: { items: [], total: 0, limit: 50, offset: 0 } });
      return;
    }

    // Default: empty success
    await route.fulfill({ json: {} });
  });
}

/** Navigate to Sessions page — chat input is always visible on /sandbox */
async function navigateToSandboxChat(page: Page) {
  const sessionsNav = page
    .locator('nav a, nav button, [role="navigation"] a')
    .filter({ hasText: /^Sessions$/ });
  await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
  await sessionsNav.first().click();
  await page.waitForLoadState('networkidle');

  // Wait for the sandbox page to load — chat input appears on all states
  await expect(
    page.getByPlaceholder(/Type your message/i)
  ).toBeVisible({ timeout: 10000 });
}

test.describe('Sandbox Skill Invocation - Request Interception', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await navigateToSandboxChat(page);
  });

  test('sends /skill:name as skill field in request body', async ({ page }) => {
    // Set up route interception to capture the POST body
    let capturedBody: Record<string, unknown> | null = null;

    await page.route('**/sandbox/*/chat/stream', async (route: Route) => {
      capturedBody = route.request().postDataJSON();
      // Abort the request — we only need to inspect the body
      await route.abort();
    });

    // Type a skill-prefixed message
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 5000 });
    await chatInput.fill('/tdd:ci analyze latest failures');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for the intercepted request
    await expect.poll(() => capturedBody, { timeout: 10000 }).not.toBeNull();

    // Verify skill and message fields
    // The component sends the full original text as `message` (including the /skill prefix)
    expect(capturedBody!.skill).toBe('tdd:ci');
    expect(capturedBody!.message).toBe('/tdd:ci analyze latest failures');
  });

  test('sends message without skill field when no / prefix', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;

    await page.route('**/sandbox/*/chat/stream', async (route: Route) => {
      capturedBody = route.request().postDataJSON();
      await route.abort();
    });

    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 5000 });
    await chatInput.fill('Hello, what can you do?');
    await page.getByRole('button', { name: /Send/i }).click();

    await expect.poll(() => capturedBody, { timeout: 10000 }).not.toBeNull();

    // No skill field should be present
    expect(capturedBody!.skill).toBeUndefined();
    expect(capturedBody!.message).toBe('Hello, what can you do?');
  });

  test('user message shows full text including /skill prefix', async ({ page }) => {
    // Abort any outgoing stream request so it doesn't hang
    await page.route('**/sandbox/*/chat/stream', async (route: Route) => {
      await route.abort();
    });

    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 5000 });
    await chatInput.fill('/rca:ci #758');
    await page.getByRole('button', { name: /Send/i }).click();

    // The user message bubble should display the full original text
    await expect(page.getByText('/rca:ci #758')).toBeVisible({ timeout: 10000 });
  });

  test('skill-only message uses skill name as message text', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;

    await page.route('**/sandbox/*/chat/stream', async (route: Route) => {
      capturedBody = route.request().postDataJSON();
      await route.abort();
    });

    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 5000 });
    await chatInput.fill('/rca:ci');
    await page.getByRole('button', { name: /Send/i }).click();

    await expect.poll(() => capturedBody, { timeout: 10000 }).not.toBeNull();

    // When only the skill name is provided (no trailing text), the full
    // original text (including the / prefix) is sent as the message
    expect(capturedBody!.skill).toBe('rca:ci');
    expect(capturedBody!.message).toBe('/rca:ci');
  });
});
