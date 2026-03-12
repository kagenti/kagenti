/**
 * Skill Whisperer E2E Test
 *
 * Verifies the / autocomplete dropdown shows agent skills
 * when the user types "/" in the chat input.
 *
 * Uses mocked API responses — no live cluster needed.
 */
import { test, expect, type Page } from '@playwright/test';

const MOCK_SKILLS = [
  {
    id: 'rca:ci',
    name: 'RCA CI',
    description: 'Root cause analysis from CI logs',
    examples: ['Analyze CI failures for PR #758'],
    tags: ['ci', 'debugging'],
  },
  {
    id: 'k8s:health',
    name: 'K8s Health',
    description: 'Check platform health including deployments and pods',
    examples: ['Check cluster health'],
    tags: ['kubernetes'],
  },
  {
    id: 'tdd:hypershift',
    name: 'TDD HyperShift',
    description: 'TDD workflow with HyperShift cluster access',
    examples: ['Run TDD cycle'],
    tags: ['tdd'],
  },
  {
    id: 'sandbox_legion',
    name: 'Sandbox Legion',
    description: 'Execute shell commands and read/write files in isolated workspace',
    examples: ['Run ls -la'],
    tags: ['shell'],
  },
];

async function setupMocks(page: Page) {
  // Mock ALL API calls to prevent Keycloak redirect
  await page.route('**/api/**', async (route) => {
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
          session_count: 5,
          active_sessions: 0,
          image: 'sandbox-agent:latest',
          created: '2026-03-01T00:00:00Z',
        }],
      });
      return;
    }

    // Agent card with skills (sandbox endpoint: /sandbox/{ns}/agent-card/{agent})
    if (url.includes('/agent-card')) {
      await route.fulfill({
        json: {
          name: 'sandbox-legion',
          description: 'A sandboxed coding assistant',
          version: '0.1.0',
          url: 'http://sandbox-legion:8000',
          capabilities: { streaming: true },
          skills: MOCK_SKILLS,
        },
      });
      return;
    }

    // Sessions list (TaskListResponse shape)
    if (url.includes('/sessions')) {
      await route.fulfill({ json: { items: [] } });
      return;
    }

    // Default: empty success
    await route.fulfill({ json: {} });
  });
}

test.describe('Skill Whisperer', () => {
  test.setTimeout(30000);

  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    // Navigate directly to sandbox page with agent pre-selected via URL param
    await page.goto('/sandbox?agent=sandbox-legion');
    await page.waitForLoadState('networkidle');

    // Wait for the sandbox page to load — chat input appears on all states
    await expect(
      page.getByPlaceholder(/Type your message/i)
    ).toBeVisible({ timeout: 10000 });

    // Wait for agent card fetch (provides skills for the whisperer)
    await page.waitForTimeout(2000);
  });

  test('shows skill dropdown when typing /', async ({ page }) => {
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 5000 });

    await chatInput.fill('/');

    const whisperer = page.locator('[data-testid="skill-whisperer"]');
    await expect(whisperer).toBeVisible({ timeout: 5000 });

    const skillOptions = page.locator('[data-testid^="skill-option-"]');
    const count = await skillOptions.count();
    console.log(`[skill-whisperer] Skill options shown: ${count}`);
    // 4 mock skills + 6 built-in tools (shell, file_read, etc.) = 10
    expect(count).toBeGreaterThanOrEqual(4);
  });

  test('filters skills as user types', async ({ page }) => {
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await chatInput.fill('/rca');

    const whisperer = page.locator('[data-testid="skill-whisperer"]');
    await expect(whisperer).toBeVisible({ timeout: 5000 });

    const skillOptions = page.locator('[data-testid^="skill-option-"]');
    expect(await skillOptions.count()).toBe(1);
    await expect(skillOptions.first()).toContainText('/rca:ci');
  });

  test('inserts skill name on click', async ({ page }) => {
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await chatInput.fill('/');

    const whisperer = page.locator('[data-testid="skill-whisperer"]');
    await expect(whisperer).toBeVisible({ timeout: 5000 });

    // Click rca:ci
    await page.locator('[data-testid="skill-option-rca:ci"]').click();

    const inputValue = await chatInput.inputValue();
    console.log(`[skill-whisperer] Input after select: "${inputValue}"`);
    expect(inputValue).toContain('/rca:ci');

    await expect(whisperer).not.toBeVisible({ timeout: 2000 });
  });

  test('dismisses on Escape', async ({ page }) => {
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await chatInput.fill('/');

    const whisperer = page.locator('[data-testid="skill-whisperer"]');
    await expect(whisperer).toBeVisible({ timeout: 5000 });

    await page.keyboard.press('Escape');
    await expect(whisperer).not.toBeVisible({ timeout: 2000 });
  });

  test('shows skill IDs and descriptions', async ({ page }) => {
    const chatInput = page.getByPlaceholder(/Type your message/i);
    await chatInput.fill('/');

    const whisperer = page.locator('[data-testid="skill-whisperer"]');
    await expect(whisperer).toBeVisible({ timeout: 5000 });

    const text = await whisperer.textContent();
    console.log(`[skill-whisperer] Dropdown: ${text?.substring(0, 300)}`);

    expect(text).toContain('/rca:ci');
    expect(text).toContain('/k8s:health');
    expect(text).toContain('/tdd:hypershift');
    expect(text).toContain('Root cause analysis');
  });
});
