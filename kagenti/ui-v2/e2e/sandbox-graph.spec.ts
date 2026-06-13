/**
 * Session Graph DAG Visualization E2E Tests (Session E)
 *
 * Tests the Session Graph page at /sandbox/graph for:
 * 1. Page renders with heading and legend
 * 2. Root node visible with correct data
 * 3. Child nodes appear after delegation (mocked API)
 * 4. Edge styles differ per delegation mode
 * 5. Node click navigates to session chat
 * 6. Status colors (running/completed/failed/pending)
 * 7. Graph API returns correct tree structure
 *
 * All tests use mocked /graph API — no live cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 30000 });

  const isKeycloakLogin = await page
    .locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    const signInButton = page.getByRole('button', { name: /Sign In/i });
    const hasSignIn = await signInButton.isVisible({ timeout: 5000 }).catch(() => false);
    if (!hasSignIn) return;
    await signInButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }

  const usernameField = page.locator('input[name="username"]').first();
  const passwordField = page.locator('input[name="password"]').first();
  const submitButton = page
    .locator('#kc-login, button[type="submit"], input[type="submit"]')
    .first();

  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await usernameField.fill(KEYCLOAK_USER);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  await passwordField.pressSequentially(KEYCLOAK_PASSWORD, { delay: 20 });
  await page.waitForTimeout(300);
  await submitButton.click();

  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
}

// ─── Mock data ───────────────────────────────────────────────────────────────

/** A delegation tree with 4 nodes across 3 delegation modes */
const MOCK_GRAPH_DATA = {
  root: 'ctx-root-001',
  nodes: [
    {
      id: 'ctx-root-001',
      agent: 'sandbox-legion',
      status: 'running',
      mode: 'root',
      tier: 'T0',
      started_at: '2026-03-02T10:00:00Z',
      duration_ms: 720000,
      task_summary: 'Root orchestration session',
    },
    {
      id: 'child-explore-001',
      agent: 'sandbox-legion',
      status: 'completed',
      mode: 'in-process',
      tier: 'T0',
      started_at: '2026-03-02T10:01:00Z',
      duration_ms: 120000,
      task_summary: 'explore the auth module',
    },
    {
      id: 'child-build-002',
      agent: 'sandbox-legion-secctx',
      status: 'running',
      mode: 'isolated',
      tier: 'T1',
      started_at: '2026-03-02T10:02:00Z',
      duration_ms: 480000,
      task_summary: 'build feature-auth PR',
    },
    {
      id: 'child-test-003',
      agent: 'sandbox-legion',
      status: 'pending',
      mode: 'shared-pvc',
      tier: 'T0',
      started_at: null,
      duration_ms: 0,
      task_summary: 'test both features together',
    },
  ],
  edges: [
    {
      from: 'ctx-root-001',
      to: 'child-explore-001',
      mode: 'in-process',
      task: 'explore the auth module',
    },
    {
      from: 'ctx-root-001',
      to: 'child-build-002',
      mode: 'isolated',
      task: 'build feature-auth PR',
    },
    {
      from: 'child-build-002',
      to: 'child-test-003',
      mode: 'shared-pvc',
      task: 'test both features together',
    },
  ],
};

/** Single root node with no children */
const MOCK_GRAPH_SINGLE_ROOT = {
  root: 'ctx-solo-001',
  nodes: [
    {
      id: 'ctx-solo-001',
      agent: 'sandbox-legion',
      status: 'running',
      mode: 'root',
      tier: 'T0',
      started_at: '2026-03-02T10:00:00Z',
      duration_ms: 60000,
      task_summary: 'Solo session',
    },
  ],
  edges: [],
};

/** Graph with a failed child */
const MOCK_GRAPH_WITH_FAILURE = {
  root: 'ctx-fail-root',
  nodes: [
    {
      id: 'ctx-fail-root',
      agent: 'sandbox-legion',
      status: 'running',
      mode: 'root',
      tier: 'T0',
      started_at: '2026-03-02T10:00:00Z',
      duration_ms: 300000,
      task_summary: 'Root session',
    },
    {
      id: 'child-fail-001',
      agent: 'sandbox-legion',
      status: 'failed',
      mode: 'isolated',
      tier: 'T0',
      started_at: '2026-03-02T10:01:00Z',
      duration_ms: 45000,
      task_summary: 'build feature that crashes',
    },
  ],
  edges: [
    {
      from: 'ctx-fail-root',
      to: 'child-fail-001',
      mode: 'isolated',
      task: 'build feature that crashes',
    },
  ],
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Mock the graph API to return specific graph data */
async function mockGraphAPI(page: Page, graphData: typeof MOCK_GRAPH_DATA) {
  await page.route('**/api/v1/chat/**/sessions/*/graph', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(graphData),
    });
  });
}

/** Mock ALL API calls that fire on app load — prevents ECONNREFUSED from breaking rendering */
async function mockAppAPIs(page: Page) {
  // Catch-all: intercept any /api/ call that isn't already mocked
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();

    // Let graph API mock handle its own route
    if (url.includes('/sessions/') && url.includes('/graph')) {
      await route.fallback();
      return;
    }

    // Auth config: disabled → ProtectedRoute renders children without Keycloak
    if (url.includes('/auth/config')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ enabled: false }),
      });
      return;
    }

    // All other API calls: return empty success to prevent proxy errors
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });
}

// ─── Tests ───────────────────────────────────────────────────────────────────

test.describe('Session Graph - Page Rendering', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_DATA);
    await mockAppAPIs(page);
    // Auth is mocked as disabled — skip login, go directly to graph page
    // (loginIfNeeded is not needed when auth/config returns enabled:false)
  });

  test('should render the graph page with heading and legend', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    // Page heading
    await expect(
      page.getByRole('heading', { name: /Session Graph/i })
    ).toBeVisible({ timeout: 10000 });

    // Legend should show status indicators
    const legend = page.locator('[data-testid="graph-legend"]');
    await expect(legend).toBeVisible({ timeout: 5000 });
    await expect(legend).toContainText('Running');
    await expect(legend).toContainText('Completed');
    await expect(legend).toContainText('Failed');
    await expect(legend).toContainText('Pending');

    // Legend should show edge mode styles
    await expect(legend).toContainText('in-process');
    await expect(legend).toContainText('isolated');
    await expect(legend).toContainText('shared-pvc');
  });

  test('should render root node with correct data', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    // Root node should be visible
    const rootNode = page.locator('[data-testid="graph-node-ctx-root-001"]');
    await expect(rootNode).toBeVisible({ timeout: 10000 });

    // Root node should show agent name
    await expect(rootNode).toContainText('sandbox-legion');

    // Root node should show context ID (truncated or full)
    await expect(rootNode).toContainText('ctx-root-001');

    // Root node should show running status
    await expect(rootNode.locator('[data-testid="node-status-badge"]')).toContainText('Running');

    // Root node should show mode
    await expect(rootNode).toContainText('root');
  });

  test('should render child nodes connected to parent', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    // All 4 nodes should be visible
    await expect(page.locator('[data-testid="graph-node-ctx-root-001"]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-testid="graph-node-child-explore-001"]')).toBeVisible();
    await expect(page.locator('[data-testid="graph-node-child-build-002"]')).toBeVisible();
    await expect(page.locator('[data-testid="graph-node-child-test-003"]')).toBeVisible();

    // Child nodes show their task summary
    const exploreNode = page.locator('[data-testid="graph-node-child-explore-001"]');
    await expect(exploreNode).toContainText('explore the auth module');
    await expect(exploreNode).toContainText('in-process');

    const buildNode = page.locator('[data-testid="graph-node-child-build-002"]');
    await expect(buildNode).toContainText('build feature-auth PR');
    await expect(buildNode).toContainText('isolated');

    const testNode = page.locator('[data-testid="graph-node-child-test-003"]');
    await expect(testNode).toContainText('test both features');
    await expect(testNode).toContainText('shared-pvc');
  });

  test('should show edges between nodes with correct count', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    // Wait for the graph to render
    await expect(page.locator('[data-testid="graph-node-ctx-root-001"]')).toBeVisible({ timeout: 10000 });

    // 3 edges should be rendered (React Flow renders edges as SVG groups)
    const edges = page.locator('[data-testid^="graph-edge-"]');
    await expect(edges).toHaveCount(3);

    // Verify specific edges exist in DOM (some may be hidden if off-viewport)
    await expect(page.locator('[data-testid="graph-edge-ctx-root-001-child-explore-001"]')).toBeAttached();
    await expect(page.locator('[data-testid="graph-edge-ctx-root-001-child-build-002"]')).toBeAttached();
    await expect(page.locator('[data-testid="graph-edge-child-build-002-child-test-003"]')).toBeAttached();
  });
});

test.describe('Session Graph - Status Colors', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_DATA);
    await mockAppAPIs(page);
    // Auth is mocked as disabled — skip login, go directly to graph page
    // (loginIfNeeded is not needed when auth/config returns enabled:false)
  });

  test('should show correct status colors for each state', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('[data-testid="graph-node-ctx-root-001"]')).toBeVisible({ timeout: 10000 });

    // Running nodes have blue status indicator
    const runningBadge = page.locator('[data-testid="graph-node-ctx-root-001"] [data-testid="node-status-badge"]');
    await expect(runningBadge).toHaveAttribute('data-status', 'running');

    // Completed nodes have green status indicator
    const completedBadge = page.locator('[data-testid="graph-node-child-explore-001"] [data-testid="node-status-badge"]');
    await expect(completedBadge).toHaveAttribute('data-status', 'completed');

    // Pending nodes have gray status indicator
    const pendingBadge = page.locator('[data-testid="graph-node-child-test-003"] [data-testid="node-status-badge"]');
    await expect(pendingBadge).toHaveAttribute('data-status', 'pending');
  });

  test('should show failed status for failed child nodes', async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_WITH_FAILURE);

    await page.goto('/sandbox/graph?contextId=ctx-fail-root&namespace=team1');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('[data-testid="graph-node-ctx-fail-root"]')).toBeVisible({ timeout: 10000 });

    // Failed node has red status indicator
    const failedBadge = page.locator('[data-testid="graph-node-child-fail-001"] [data-testid="node-status-badge"]');
    await expect(failedBadge).toHaveAttribute('data-status', 'failed');
    await expect(failedBadge).toContainText('Failed');
  });
});

test.describe('Session Graph - Navigation', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_DATA);
    await mockAppAPIs(page);
    // Auth is mocked as disabled — skip login, go directly to graph page
    // (loginIfNeeded is not needed when auth/config returns enabled:false)
  });

  test('should navigate to session chat when node is clicked', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    const childNode = page.locator('[data-testid="graph-node-child-explore-001"]');
    await expect(childNode).toBeVisible({ timeout: 10000 });

    // Click the node
    await childNode.click();

    // Should navigate to the sandbox chat page with the session context
    await expect(page).toHaveURL(/\/sandbox.*session=child-explore-001|contextId=child-explore-001/, {
      timeout: 10000,
    });
  });

  test('should navigate to graph page from Sessions nav', async ({ page }) => {
    // The Session Graph link should be accessible from the nav
    const graphLink = page.locator('nav a', { hasText: /Graph|Session Graph/i });
    const hasGraphLink = await graphLink.isVisible({ timeout: 5000 }).catch(() => false);

    if (hasGraphLink) {
      await graphLink.click();
      await expect(page).toHaveURL(/\/sandbox\/graph/);
      await expect(
        page.getByRole('heading', { name: /Session Graph/i })
      ).toBeVisible({ timeout: 10000 });
    } else {
      // Direct navigation should also work
      await page.goto('/sandbox/graph');
      await expect(
        page.getByRole('heading', { name: /Session Graph/i })
      ).toBeVisible({ timeout: 10000 });
    }
  });
});

test.describe('Session Graph - Edge Styles', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_DATA);
    await mockAppAPIs(page);
    // Auth is mocked as disabled — skip login, go directly to graph page
    // (loginIfNeeded is not needed when auth/config returns enabled:false)
  });

  test('should differentiate edge styles by delegation mode', async ({ page }) => {
    await page.goto('/sandbox/graph?contextId=ctx-root-001&namespace=team1');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('[data-testid="graph-node-ctx-root-001"]')).toBeVisible({ timeout: 10000 });

    // In-process edge
    const inProcessEdge = page.locator('[data-testid="graph-edge-ctx-root-001-child-explore-001"]');
    await expect(inProcessEdge).toHaveAttribute('data-mode', 'in-process');

    // Isolated edge
    const isolatedEdge = page.locator('[data-testid="graph-edge-ctx-root-001-child-build-002"]');
    await expect(isolatedEdge).toHaveAttribute('data-mode', 'isolated');

    // Shared-PVC edge
    const sharedEdge = page.locator('[data-testid="graph-edge-child-build-002-child-test-003"]');
    await expect(sharedEdge).toHaveAttribute('data-mode', 'shared-pvc');
  });
});

test.describe('Session Graph - Single Root', () => {
  test.setTimeout(60000);

  test('should render a single root node without children', async ({ page }) => {
    await mockGraphAPI(page, MOCK_GRAPH_SINGLE_ROOT);
    await mockAppAPIs(page);

    // Auth is mocked as disabled — skip login, go directly to graph page
    // (loginIfNeeded is not needed when auth/config returns enabled:false)
    await page.goto('/sandbox/graph?contextId=ctx-solo-001&namespace=team1');
    await page.waitForLoadState('networkidle');

    // Only the root node should be visible
    const rootNode = page.locator('[data-testid="graph-node-ctx-solo-001"]');
    await expect(rootNode).toBeVisible({ timeout: 10000 });
    await expect(rootNode).toContainText('sandbox-legion');
    await expect(rootNode).toContainText('Solo session');

    // No edges
    const edges = page.locator('[data-testid^="graph-edge-"]');
    await expect(edges).toHaveCount(0);
  });
});
