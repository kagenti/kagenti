/**
 * Sessions Table Page E2E Tests
 *
 * Tests the SessionsTablePage functionality including:
 * - Page structure (title, namespace selector, type filter)
 * - Type filtering (All / Root / Child / Passover)
 * - Session data display (truncated IDs, titles, badges, parent links)
 * - Empty state handling
 * - Error handling
 * - Delete modal interaction
 *
 * All API calls are mocked — no cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockSessions = {
  items: [
    {
      id: 'task-1',
      context_id: 'ctx-abc123def456',
      kind: 'sandbox-session',
      status: { state: 'completed' },
      metadata: {
        title: 'Fix auth bug',
        session_type: 'root',
        agent_variant: 'sandbox-legion',
        created_at: '2026-03-01T10:00:00Z',
      },
    },
    {
      id: 'task-2',
      context_id: 'ctx-child789xyz',
      kind: 'sandbox-session',
      status: { state: 'working' },
      metadata: {
        title: 'Research sub-task',
        session_type: 'child',
        parent_context_id: 'ctx-abc123def456',
        agent_variant: 'sandbox-basic',
        created_at: '2026-03-01T11:00:00Z',
      },
    },
    {
      id: 'task-3',
      context_id: 'ctx-pass456abc',
      kind: 'sandbox-session',
      status: { state: 'completed' },
      metadata: {
        title: 'Continued from ctx-abc',
        session_type: 'passover',
        passover_from: 'ctx-abc123def456',
        created_at: '2026-03-01T12:00:00Z',
      },
    },
  ],
  total: 3,
  limit: 50,
  offset: 0,
};

const EMPTY_SESSIONS_RESPONSE = { items: [], total: 0, limit: 50, offset: 0 };

// ---------------------------------------------------------------------------
// Helper: mock backend APIs so the app can boot without a running backend
// ---------------------------------------------------------------------------
async function mockBackendAPIs(page: Page) {
  await page.route('**/api/v1/auth/config', (route) => {
    route.fulfill({
      status: 200,
      body: JSON.stringify({ enabled: false }),
      contentType: 'application/json',
    });
  });
  await page.route('**/api/v1/namespaces**', (route) => {
    route.fulfill({
      status: 200,
      body: JSON.stringify({ namespaces: ['team1', 'team2'] }),
      contentType: 'application/json',
    });
  });
}

// ---------------------------------------------------------------------------
// Group 1: Page Structure
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Page Structure', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(mockSessions),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');
  });

  test('should display page with Sessions title', async ({ page }) => {
    await expect(
      page.getByRole('heading', { name: /Sessions/i })
    ).toBeVisible({ timeout: 10000 });
  });

  test('should have namespace selector', async ({ page }) => {
    const namespaceSelector = page
      .locator('[aria-label="Select namespace"]')
      .or(page.getByRole('button', { name: /team1/i }));
    await expect(namespaceSelector.first()).toBeVisible({ timeout: 10000 });
  });

  test('should show type filter toggle group', async ({ page }) => {
    const toggleGroup = page.locator('[aria-label="Session type filter"]');
    await expect(toggleGroup).toBeVisible({ timeout: 10000 });
  });

  test('should show All filter selected by default', async ({ page }) => {
    const allButton = page.locator('#filter-all');
    await expect(allButton).toBeVisible({ timeout: 10000 });
    // PatternFly ToggleGroupItem gets pf-m-selected when active
    await expect(allButton).toHaveClass(/pf-m-selected/);
  });

  test('should display table when sessions exist', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // Verify column headers
    await expect(page.getByRole('columnheader', { name: /Session ID/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Title/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Type/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Parent/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Status/i })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: /Created/i })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 2: Type Filtering
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Type Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(mockSessions),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');
  });

  test('should filter to root sessions only', async ({ page }) => {
    await page.locator('#filter-root').click();

    // Only the root session should be visible
    await expect(page.getByText('Fix auth bug')).toBeVisible();
    await expect(page.getByText('Research sub-task')).not.toBeVisible();
    await expect(page.getByText('Continued from ctx-abc')).not.toBeVisible();
  });

  test('should filter to child sessions only', async ({ page }) => {
    await page.locator('#filter-child').click();

    // Only the child session should be visible
    await expect(page.getByText('Research sub-task')).toBeVisible();
    await expect(page.getByText('Fix auth bug')).not.toBeVisible();
    await expect(page.getByText('Continued from ctx-abc')).not.toBeVisible();
  });

  test('should filter to passover sessions only', async ({ page }) => {
    await page.locator('#filter-passover').click();

    // Only the passover session should be visible
    await expect(page.getByText('Continued from ctx-abc')).toBeVisible();
    await expect(page.getByText('Fix auth bug')).not.toBeVisible();
    await expect(page.getByText('Research sub-task')).not.toBeVisible();
  });

  test('should show all sessions when All selected', async ({ page }) => {
    // First switch to root, then back to all
    await page.locator('#filter-root').click();
    await expect(page.getByText('Research sub-task')).not.toBeVisible();

    await page.locator('#filter-all').click();

    await expect(page.getByText('Fix auth bug')).toBeVisible();
    await expect(page.getByText('Research sub-task')).toBeVisible();
    await expect(page.getByText('Continued from ctx-abc')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 3: Session Data Display
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Data Display', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(mockSessions),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');
  });

  test('should show truncated session IDs', async ({ page }) => {
    // context_id "ctx-abc123def456" truncated to first 8 chars + "..."
    // It appears in both Session ID and Parent columns, so scope to Session ID cells
    const sessionIdCells = page.locator('[data-label="Session ID"]');
    await expect(sessionIdCells.getByText('ctx-abc1...')).toBeVisible({ timeout: 10000 });
    // context_id "ctx-child789xyz" truncated
    await expect(sessionIdCells.getByText('ctx-chil...')).toBeVisible();
    // context_id "ctx-pass456abc" truncated
    await expect(sessionIdCells.getByText('ctx-pass...')).toBeVisible();
  });

  test('should show session title', async ({ page }) => {
    await expect(page.getByText('Fix auth bug')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Research sub-task')).toBeVisible();
    await expect(page.getByText('Continued from ctx-abc')).toBeVisible();
  });

  test('should show type badges with correct colors', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // PatternFly Label colors use pf-m-<color> class
    // root = blue
    const rootBadge = page.locator('.pf-v5-c-label.pf-m-blue').filter({ hasText: 'root' });
    await expect(rootBadge.first()).toBeVisible();

    // child = cyan
    const childBadge = page.locator('.pf-v5-c-label.pf-m-cyan').filter({ hasText: 'child' });
    await expect(childBadge.first()).toBeVisible();

    // passover = purple
    const passoverBadge = page.locator('.pf-v5-c-label.pf-m-purple').filter({ hasText: 'passover' });
    await expect(passoverBadge.first()).toBeVisible();
  });

  test('should show parent link for child sessions', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // The child session row should have a parent link showing truncated parent_context_id
    // parent_context_id "ctx-abc123def456" truncated to "ctx-abc1..."
    const parentCell = page.locator('[data-label="Parent"]');
    const parentLinks = parentCell.getByRole('link').or(
      parentCell.locator('button.pf-v5-c-button.pf-m-link, a')
    );

    // There should be at least one parent link (the child session has a parent)
    let found = false;
    const count = await parentCell.count();
    for (let i = 0; i < count; i++) {
      const text = await parentCell.nth(i).textContent();
      if (text && text.includes('ctx-abc1...')) {
        found = true;
        break;
      }
    }
    expect(found).toBe(true);
  });

  test('should show status badges', async ({ page }) => {
    const table = page.getByRole('grid');
    await expect(table).toBeVisible({ timeout: 10000 });

    // "completed" state maps to "Completed" label (blue)
    const completedBadge = page.locator('.pf-v5-c-label.pf-m-blue').filter({ hasText: 'Completed' });
    await expect(completedBadge.first()).toBeVisible();

    // "working" state maps to "Running" label (green)
    const runningBadge = page.locator('.pf-v5-c-label.pf-m-green').filter({ hasText: 'Running' });
    await expect(runningBadge.first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Group 4: Empty State
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Empty State', () => {
  test('should show empty state when no sessions', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(EMPTY_SESSIONS_RESPONSE),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');

    await expect(
      page.getByRole('heading', { name: /No sessions found/i })
    ).toBeVisible({ timeout: 10000 });
  });

  test('should show filtered empty state message', async ({ page }) => {
    await mockBackendAPIs(page);
    // Return sessions with only root type so filtering to child yields empty
    const rootOnlySessions = {
      items: [mockSessions.items[0]], // only the root session
      total: 1,
      limit: 50,
      offset: 0,
    };
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(rootOnlySessions),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');

    // Switch to child filter - no child sessions exist
    await page.locator('#filter-child').click();

    await expect(
      page.getByText(/No child sessions found/i)
    ).toBeVisible({ timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Group 5: Error Handling
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Error Handling', () => {
  test('should show error state when API fails', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 500,
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/sessions');

    await expect(
      page.getByText(/Error loading sessions/i)
    ).toBeVisible({ timeout: 10000 });
  });

  test('should call sessions API on load', async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(mockSessions),
        contentType: 'application/json',
      });
    });

    let apiCalled = false;

    page.on('response', (response) => {
      if (response.url().includes('/api/v1/sandbox/') && response.url().includes('/sessions')) {
        apiCalled = true;
      }
    });

    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');

    expect(apiCalled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Group 6: Delete Modal
// ---------------------------------------------------------------------------
test.describe('Sessions Table - Delete Modal', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackendAPIs(page);
    await page.route('**/api/v1/sandbox/*/sessions*', (route) => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(mockSessions),
        contentType: 'application/json',
      });
    });
    await page.goto('/sessions');
    await page.waitForLoadState('networkidle');
  });

  test('should open delete modal from actions menu', async ({ page }) => {
    // Wait for the table to render
    await expect(page.getByRole('grid')).toBeVisible({ timeout: 10000 });

    // Click the actions menu (kebab) for the first session row
    const actionsToggle = page.getByRole('button', { name: /Actions menu/i });
    await expect(actionsToggle.first()).toBeVisible();
    await actionsToggle.first().click();

    // Click "Delete session" in the dropdown
    await page.getByRole('menuitem', { name: /Delete session/i }).click();

    // Verify the delete modal is visible
    await expect(page.getByText(/Delete session\?/i)).toBeVisible();
    await expect(page.getByText(/will be permanently deleted/i)).toBeVisible();
  });

  test('should close modal on cancel', async ({ page }) => {
    await expect(page.getByRole('grid')).toBeVisible({ timeout: 10000 });

    // Open the delete modal
    const actionsToggle = page.getByRole('button', { name: /Actions menu/i });
    await actionsToggle.first().click();
    await page.getByRole('menuitem', { name: /Delete session/i }).click();

    // Verify modal is open
    await expect(page.getByText(/Delete session\?/i)).toBeVisible();

    // Click Cancel
    const cancelButton = page
      .getByRole('dialog')
      .getByRole('button', { name: /Cancel/i });
    await cancelButton.click();

    // Verify modal is closed
    await expect(page.getByText(/Delete session\?/i)).not.toBeVisible();
  });
});
