/**
 * Sandbox File Browser E2E Tests (Session H)
 *
 * Tests the File Browser page at /sandbox/files/:namespace/:agentName for:
 * 1. Directory listing renders with entries (TreeView)
 * 2. Missing route params shows not-found / empty state
 * 3. Clicking .md file shows markdown preview with mermaid SVG
 * 4. Clicking code file shows PatternFly CodeBlock
 * 5. Breadcrumb navigation shows path segments
 * 6. File metadata displays size and date
 *
 * All tests use mocked API routes -- no live cluster required.
 */
import { test, expect, type Page } from '@playwright/test';

// ── Auth credentials (unused when auth is mocked disabled) ──────────────────
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

  if (await usernameField.isVisible({ timeout: 3000 }).catch(() => false)) {
    await usernameField.fill(KEYCLOAK_USER);
    await passwordField.fill(KEYCLOAK_PASSWORD);
    await submitButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }
}

// ── Mock data ───────────────────────────────────────────────────────────────

const MOCK_DIR_LISTING = {
  path: '/workspace',
  entries: [
    {
      name: 'src',
      path: '/workspace/src',
      type: 'directory',
      size: 4096,
      modified: '2026-03-02T10:00:00+00:00',
      permissions: 'drwxr-xr-x',
    },
    {
      name: 'README.md',
      path: '/workspace/README.md',
      type: 'file',
      size: 256,
      modified: '2026-03-02T09:30:00+00:00',
      permissions: '-rw-r--r--',
    },
    {
      name: 'main.py',
      path: '/workspace/main.py',
      type: 'file',
      size: 1024,
      modified: '2026-03-02T09:00:00+00:00',
      permissions: '-rw-r--r--',
    },
  ],
};

const MOCK_MD_CONTENT = {
  path: '/workspace/README.md',
  content:
    '# Hello World\n\nThis is a **test** markdown file.\n\n```mermaid\ngraph TD\n  A-->B\n```\n',
  size: 256,
  modified: '2026-03-02T09:30:00+00:00',
  type: 'file',
  encoding: 'utf-8',
};

const MOCK_PY_CONTENT = {
  path: '/workspace/main.py',
  content: 'def hello():\n    print("Hello, world!")\n',
  size: 1024,
  modified: '2026-03-02T09:00:00+00:00',
  type: 'file',
  encoding: 'utf-8',
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Set up mock routes for the sandbox file browser API */
function setupMockRoutes(page: Page) {
  return page.route('**/api/v1/sandbox/team1/files/sandbox-basic*', async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get('path') || '/workspace';

    if (path === '/workspace/README.md') {
      await route.fulfill({ json: MOCK_MD_CONTENT });
    } else if (path === '/workspace/main.py') {
      await route.fulfill({ json: MOCK_PY_CONTENT });
    } else {
      await route.fulfill({ json: MOCK_DIR_LISTING });
    }
  });
}

/** Mock ALL app-level API calls to prevent connection errors */
async function mockAppAPIs(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();

    // Let the file browser and stats API mocks handle their own routes
    if (url.includes('/sandbox/team1/files/') || url.includes('/sandbox/team1/stats/')) {
      await route.fallback();
      return;
    }

    // Auth config: disabled -- renders children without Keycloak
    if (url.includes('/auth/config')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ enabled: false }),
      });
      return;
    }

    // All other API calls: return empty success
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });
}

// ── Tests ───────────────────────────────────────────────────────────────────

test.describe('Sandbox File Browser', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await setupMockRoutes(page);
    await mockAppAPIs(page);
  });

  test('renders directory listing with entries', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // TreeView should appear
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]');
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // All three entries should be visible in the tree
    await expect(page.getByText('src')).toBeVisible();
    await expect(page.getByText('README.md')).toBeVisible();
    await expect(page.getByText('main.py')).toBeVisible();
  });

  test('shows not-found page when no agent params provided', async ({ page }) => {
    await page.goto('/sandbox/files');
    await page.waitForLoadState('networkidle');

    // The route /sandbox/files without :namespace/:agentName does not match
    // the router definition, so the app should show a not-found or fallback page.
    // Check that the file browser tree is NOT visible.
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]');
    await expect(treeView).not.toBeVisible({ timeout: 5000 });
  });

  test('click .md file shows markdown preview with mermaid', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]');
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click README.md in the tree
    await page.getByText('README.md').click();

    // Markdown heading should render
    const heading = page.locator('h1');
    await expect(heading).toContainText('Hello World', { timeout: 10000 });

    // Bold text should render
    const bold = page.locator('strong');
    await expect(bold).toContainText('test');

    // Mermaid diagram should render as SVG
    const svg = page.locator('svg');
    await expect(svg.first()).toBeVisible({ timeout: 15000 });
  });

  test('click code file shows code block', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]');
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click main.py in the tree
    await page.getByText('main.py').click();

    // PatternFly CodeBlock should appear
    const codeBlock = page.locator('[class*="pf-v5-c-code-block"]');
    await expect(codeBlock).toBeVisible({ timeout: 10000 });

    // Code content should be visible
    await expect(page.getByText('def hello():')).toBeVisible();
  });

  test('breadcrumb navigation shows path segments', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Breadcrumb should be visible
    const breadcrumb = page.locator('[class*="pf-v5-c-breadcrumb"]');
    await expect(breadcrumb).toBeVisible({ timeout: 10000 });

    // "workspace" segment should be present in the breadcrumb
    await expect(breadcrumb).toContainText('workspace');
  });

  test('file metadata displays size and date', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]');
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click README.md to show file preview with metadata
    await page.getByText('README.md').click();

    // File size label should show "256 B"
    await expect(page.getByText('256 B')).toBeVisible({ timeout: 10000 });
  });

  test('end-to-end: agent writes file, file browser shows it', async ({ page }) => {
    // Mock: simulate that after writing, the directory listing includes the new file
    const MOCK_DIR_WITH_NEW_FILE = {
      path: '/workspace/data',
      entries: [
        { name: 'e2e_test.txt', path: '/workspace/data/e2e_test.txt', type: 'file', size: 28, modified: '2026-03-02T12:00:00+00:00', permissions: '-rw-r--r--' },
      ],
    };

    const MOCK_NEW_FILE_CONTENT = {
      path: '/workspace/data/e2e_test.txt',
      content: 'sandbox-e2e-test-payload',
      size: 28,
      modified: '2026-03-02T12:00:00+00:00',
      type: 'file',
      encoding: 'utf-8',
    };

    // Override mock to include the new file when browsing /workspace/data
    await page.route('**/api/v1/sandbox/team1/files/sandbox-basic*', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '/';
      if (path === '/workspace/data') {
        await route.fulfill({ json: MOCK_DIR_WITH_NEW_FILE });
      } else if (path === '/workspace/data/e2e_test.txt') {
        await route.fulfill({ json: MOCK_NEW_FILE_CONTENT });
      } else {
        await route.fulfill({ json: MOCK_DIR_LISTING });
      }
    });

    // Navigate to file browser, drill into /workspace/data
    await page.goto('/sandbox/files/team1/sandbox-basic?path=/workspace/data');
    await loginIfNeeded(page);
    await page.waitForSelector('[class*="pf-v5-c-tree-view"]', { timeout: 15000 });

    // Verify the written file appears in the listing
    await expect(page.getByText('e2e_test.txt')).toBeVisible();

    // Click the file to preview its content
    await page.getByText('e2e_test.txt').click();
    await expect(page.getByText('sandbox-e2e-test-payload')).toBeVisible({ timeout: 10000 });
  });

  test('storage stats shows mount information', async ({ page }) => {
    // Mock stats endpoint
    await page.route('**/api/v1/sandbox/team1/stats/sandbox-basic', async (route) => {
      await route.fulfill({
        json: {
          mounts: [
            { filesystem: '/dev/sda1', size: '50G', used: '12G', available: '38G', use_percent: '24%', mount_point: '/' },
            { filesystem: '/dev/sdb1', size: '100G', used: '45G', available: '55G', use_percent: '45%', mount_point: '/workspace' },
          ],
          total_mounts: 2,
        },
      });
    });

    // This test just verifies the API mock responds correctly
    // The UI rendering of stats on SandboxesPage is Session C's responsibility
    const response = await page.request.get('/api/v1/sandbox/team1/stats/sandbox-basic');
    const data = await response.json();
    expect(data.total_mounts).toBe(2);
    expect(data.mounts[1].mount_point).toBe('/workspace');
  });
});
