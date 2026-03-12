/**
 * Sandbox HITL (Human-in-the-Loop) Approval Flow E2E Tests
 *
 * Tests the HITL approval flow in the SandboxPage (/sandbox):
 * 1. HITL event rendering — "Approval Required" label, Approve/Deny buttons
 * 2. HITL button actions — approve and deny call the correct backend endpoints
 *
 * All API calls are mocked — no cluster or running agent required.
 *
 * The SandboxPage SSE streaming handler detects `hitl_request` events and
 * renders them inline as ToolCallStep cards with Approve and Deny buttons.
 * When the user clicks Approve or Deny, the page calls the sandbox session
 * approve/deny endpoint (POST /api/v1/sandbox/{ns}/sessions/{contextId}/approve|deny).
 *
 * IMPORTANT: The SandboxPage navigated with ?session= pre-set to avoid a
 * race condition where the SSE response's session_id triggers loadInitialHistory,
 * which clears the in-memory messages before they render.
 */
import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TEST_NAMESPACE = 'team1';
const TEST_AGENT = 'sandbox-legion';
/** Pre-set session ID — must match the session_id in SSE responses. */
const TEST_SESSION_ID = 'hitl-test-session';

const EMPTY_SESSION_LIST = { items: [], total: 0, limit: 20, offset: 0 };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Intercept ALL /api/ requests with a single handler function.
 * Test-specific handlers for /chat/stream, /approve, /deny are registered
 * separately and use route.fallback() from this catch-all.
 */
async function mockAllAPIs(page: Page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();

    // Auth config — disable auth so ProtectedRoute renders children
    if (url.includes('/auth/config')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ enabled: false }),
        contentType: 'application/json',
      });
    }

    // Namespaces
    if (url.includes('/namespaces')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ namespaces: [TEST_NAMESPACE] }),
        contentType: 'application/json',
      });
    }

    // Sandbox agents
    if (url.includes('/sandbox/') && url.includes('/agents')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify([
          { name: TEST_AGENT, namespace: TEST_NAMESPACE, status: 'running' },
        ]),
        contentType: 'application/json',
      });
    }

    // Session history — return empty so the page doesn't clobber messages
    if (url.includes('/history')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify({ messages: [], has_more: false }),
        contentType: 'application/json',
      });
    }

    // Approve, deny, chat/stream — fall through to test-specific handlers
    if (url.includes('/approve') || url.includes('/deny') || url.includes('/chat')) {
      return route.fallback();
    }

    // Sidecars — must be checked before the generic /sessions catch-all
    if (url.includes('/sidecars')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify([]),
        contentType: 'application/json',
      });
    }

    // Sessions list or detail
    if (url.includes('/sessions')) {
      return route.fulfill({
        status: 200,
        body: JSON.stringify(EMPTY_SESSION_LIST),
        contentType: 'application/json',
      });
    }

    // Default: return empty 200 for any other API call
    return route.fulfill({
      status: 200,
      body: JSON.stringify({}),
      contentType: 'application/json',
    });
  });
}

/**
 * Build an SSE body string that includes a hitl_request event.
 */
function buildHitlSSEBody(options?: {
  taskId?: string;
  reason?: string;
}) {
  const taskId = options?.taskId ?? 'task-123';
  const reason = options?.reason ?? 'Command requires approval';

  const hitlEvent = JSON.stringify({
    session_id: TEST_SESSION_ID,
    event: {
      type: 'hitl_request',
      taskId,
      state: 'INPUT_REQUIRED',
      final: false,
      message: reason,
    },
    content: reason,
  });

  return `data: ${hitlEvent}\n\n`;
}

/**
 * Navigate to the sandbox page with a pre-set session parameter.
 *
 * The ?session= param ensures contextId is already set when the component
 * mounts. This prevents the SSE response from triggering loadInitialHistory,
 * which would clear in-memory messages before they render.
 */
async function goToSandbox(page: Page) {
  await page.goto(`/sandbox?session=${TEST_SESSION_ID}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(
    page.locator('textarea[aria-label="Message input"]').first(),
  ).toBeVisible({ timeout: 20000 });
}

/**
 * Type a message and click Send.
 */
async function sendMessage(page: Page, text: string) {
  const textarea = page.locator('textarea[aria-label="Message input"]').first();
  await textarea.click();
  await textarea.pressSequentially(text, { delay: 20 });
  await page.getByRole('button', { name: /Send/i }).click();
}

// ---------------------------------------------------------------------------
// Group 1: HITL Event Rendering
// ---------------------------------------------------------------------------

test.describe('Sandbox HITL - Event Rendering', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page);
  });

  test('should show Approval Required label for HITL events', async ({ page }) => {
    await page.route('**/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: buildHitlSSEBody({
          reason: 'Command "rm -rf /tmp/old" requires approval',
        }),
      });
    });

    await goToSandbox(page);
    await sendMessage(page, 'Clean up temp files');

    // The ToolCallStep renders "Approval Required" as a bold heading
    await expect(page.getByText('Approval Required').first()).toBeVisible({
      timeout: 15000,
    });
  });

  test('should show Approve and Deny buttons for HITL events', async ({ page }) => {
    await page.route('**/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: buildHitlSSEBody({
          reason: 'Dangerous command needs confirmation',
        }),
      });
    });

    await goToSandbox(page);
    await sendMessage(page, 'Delete the web pod');

    // Wait for the HITL card
    await expect(page.getByText('Approval Required').first()).toBeVisible({
      timeout: 15000,
    });

    // Both Approve and Deny buttons should be present
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Deny' })).toBeVisible();
  });

  test('should display HITL reason message in the approval card', async ({ page }) => {
    const reason = 'Agent wants to run: rm -rf /important-data';

    await page.route('**/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: buildHitlSSEBody({ reason }),
      });
    });

    await goToSandbox(page);
    await sendMessage(page, 'Execute cleanup');

    // The reason text should be visible in the HITL card
    await expect(page.getByText(reason).first()).toBeVisible({ timeout: 15000 });
  });
});

// ---------------------------------------------------------------------------
// Group 2: HITL Button Actions
// ---------------------------------------------------------------------------

test.describe('Sandbox HITL - Button Actions', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page);
  });

  test('should call approve endpoint when Approve clicked', async ({ page }) => {
    let approveEndpointCalled = false;

    // SSE stream returning a HITL request
    await page.route('**/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: buildHitlSSEBody({
          taskId: 'task-approve-test',
          reason: 'Confirm execution of dangerous command',
        }),
      });
    });

    // Approve endpoint
    await page.route('**/approve', async (route) => {
      approveEndpointCalled = true;
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ status: 'approved', context_id: TEST_SESSION_ID }),
        contentType: 'application/json',
      });
    });

    await goToSandbox(page);
    await sendMessage(page, 'Run the dangerous command');

    // Wait for HITL card
    await expect(page.getByText('Approval Required').first()).toBeVisible({
      timeout: 15000,
    });

    // Click Approve
    await page.getByRole('button', { name: 'Approve' }).click();

    // Verify: the Approved label appears (local UI state change)
    await expect(page.getByText('Approved').first()).toBeVisible({ timeout: 5000 });

    // Verify: the approve endpoint was called
    expect(approveEndpointCalled).toBe(true);
  });

  test('should call deny endpoint when Deny clicked', async ({ page }) => {
    let denyEndpointCalled = false;

    // SSE stream returning a HITL request
    await page.route('**/chat/stream', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: buildHitlSSEBody({
          taskId: 'task-deny-test',
          reason: 'Confirm deletion of production database',
        }),
      });
    });

    // Deny endpoint
    await page.route('**/deny', async (route) => {
      denyEndpointCalled = true;
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ status: 'denied', context_id: TEST_SESSION_ID }),
        contentType: 'application/json',
      });
    });

    await goToSandbox(page);
    await sendMessage(page, 'Drop the production database');

    // Wait for HITL card
    await expect(page.getByText('Approval Required').first()).toBeVisible({
      timeout: 15000,
    });

    // Click Deny
    await page.getByRole('button', { name: 'Deny' }).click();

    // Verify: the Denied label appears (local UI state change)
    await expect(page.getByText('Denied').first()).toBeVisible({ timeout: 5000 });

    // Verify: the deny endpoint was called
    expect(denyEndpointCalled).toBe(true);
  });
});
