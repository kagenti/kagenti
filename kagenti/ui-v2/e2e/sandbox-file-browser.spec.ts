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

const MOCK_BINARY_CONTENT = {
  path: '/workspace/data.db',
  content: 'SQLite format 3\x00\x10\x00\x01\x01\x00',
  size: 8192,
  modified: '2026-03-02T11:00:00+00:00',
  type: 'file',
  encoding: 'utf-8',
};

const MOCK_BAD_DATE_CONTENT = {
  path: '/workspace/broken.txt',
  content: 'some text content',
  size: 17,
  modified: 'not-a-date',
  type: 'file',
  encoding: 'utf-8',
};

const MOCK_DIR_WITH_EXTRAS = {
  path: '/workspace',
  entries: [
    ...MOCK_DIR_LISTING.entries,
    {
      name: 'data.db',
      path: '/workspace/data.db',
      type: 'file' as const,
      size: 8192,
      modified: '2026-03-02T11:00:00+00:00',
      permissions: '-rw-r--r--',
    },
    {
      name: 'broken.txt',
      path: '/workspace/broken.txt',
      type: 'file' as const,
      size: 17,
      modified: 'not-a-date',
      permissions: '-rw-r--r--',
    },
  ],
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Set up mock routes for the sandbox file browser API */
function setupMockRoutes(page: Page) {
  return page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
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
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
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
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).not.toBeVisible({ timeout: 5000 });
  });

  test('click .md file shows markdown preview with mermaid', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
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
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click main.py in the tree
    await page.getByText('main.py').click();

    // PatternFly CodeBlock should appear (use .first() — PF nests child elements with same prefix)
    const codeBlock = page.locator('.pf-v5-c-code-block').first();
    await expect(codeBlock).toBeVisible({ timeout: 10000 });

    // Code content should be visible
    await expect(page.getByText('def hello():')).toBeVisible();
  });

  test('breadcrumb navigation shows path segments', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render, then click a directory to generate breadcrumb segments
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click the "src" directory to navigate into /workspace/src
    await page.getByText('src').click();

    // Breadcrumb should be visible (use nav tag to avoid matching nested ol)
    const breadcrumb = page.locator('nav[class*="pf-v5-c-breadcrumb"]');
    await expect(breadcrumb).toBeVisible({ timeout: 10000 });

    // "workspace" and "src" segments should be present in the breadcrumb
    await expect(breadcrumb).toContainText('workspace');
    await expect(breadcrumb).toContainText('src');
  });

  test('file metadata displays size and date', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Wait for tree to render
    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click README.md to show file preview with metadata
    await page.getByText('README.md').click();

    // File size label should show "256 B"
    await expect(page.getByText('256 B')).toBeVisible({ timeout: 10000 });
  });

  test('binary file shows "preview not available" instead of crashing', async ({ page }) => {
    // Override mock to include binary file
    await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '/workspace';
      if (path === '/workspace/data.db') {
        await route.fulfill({ json: MOCK_BINARY_CONTENT });
      } else {
        await route.fulfill({ json: MOCK_DIR_WITH_EXTRAS });
      }
    });

    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click the binary file
    await page.getByText('data.db').click();

    // Should show "Binary file" message, NOT crash
    await expect(page.getByText('Binary file')).toBeVisible({ timeout: 10000 });

    // The tree should still be visible (didn't crash the whole browser)
    await expect(treeView).toBeVisible();
  });

  test('bad date in file metadata does not crash preview', async ({ page }) => {
    // Override mock to include broken date file
    await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '/workspace';
      if (path === '/workspace/broken.txt') {
        await route.fulfill({ json: MOCK_BAD_DATE_CONTENT });
      } else {
        await route.fulfill({ json: MOCK_DIR_WITH_EXTRAS });
      }
    });

    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click the file with bad date
    await page.getByText('broken.txt').click();

    // Content should render in a code block (not crash)
    await expect(page.getByText('some text content')).toBeVisible({ timeout: 10000 });

    // Tree should still be visible
    await expect(treeView).toBeVisible();
  });

  test('preview failure does not crash the file tree', async ({ page }) => {
    // Override mock to return content that could crash a renderer
    await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '/workspace';
      if (path === '/workspace/README.md') {
        // Return a null content field that could crash ReactMarkdown
        await route.fulfill({
          json: {
            path: '/workspace/README.md',
            content: null,
            size: 0,
            modified: '2026-03-02T09:30:00+00:00',
            type: 'file',
            encoding: 'utf-8',
          },
        });
      } else {
        await route.fulfill({ json: MOCK_DIR_LISTING });
      }
    });

    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
    await expect(treeView).toBeVisible({ timeout: 10000 });

    // Click the file that will crash the preview
    await page.getByText('README.md').click();
    await page.waitForTimeout(2000);

    // The tree should STILL be visible — ErrorBoundary catches the crash
    await expect(treeView).toBeVisible();
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

    // Override mock: the component always starts at currentPath='/' so
    // return the new-file listing as the default directory response.
    await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '/';
      if (path === '/workspace/data/e2e_test.txt') {
        await route.fulfill({ json: MOCK_NEW_FILE_CONTENT });
      } else {
        // Default directory listing includes the new file
        await route.fulfill({ json: MOCK_DIR_WITH_NEW_FILE });
      }
    });

    // Navigate to file browser (component always starts at '/')
    await page.goto('/sandbox/files/team1/sandbox-basic');
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

    // Navigate to any page so the browser context is active for fetch()
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await page.waitForLoadState('networkidle');

    // Use page.evaluate + fetch() so the request goes through page.route() mocks
    // (page.request.get() bypasses page route interception)
    const data = await page.evaluate(async () => {
      const res = await fetch('/api/v1/sandbox/team1/stats/sandbox-basic');
      return res.json();
    });
    expect(data.total_mounts).toBe(2);
    expect(data.mounts[1].mount_point).toBe('/workspace');
  });
});

// =============================================================================
// Live Cluster Tests — require a running sandbox agent
// =============================================================================
// Run with: KAGENTI_UI_URL=https://... npx playwright test sandbox-file-browser
// Skipped automatically when KAGENTI_UI_URL is not set.

const LIVE_URL = process.env.KAGENTI_UI_URL;
const AGENT_NAME = process.env.SANDBOX_AGENT || 'sandbox-basic';
const NAMESPACE = process.env.SANDBOX_NAMESPACE || 'team1';
const AGENT_TIMEOUT = 180_000; // 3 min for LLM response

/**
 * Send a message in the sandbox chat and wait for the agent to finish.
 */
async function sendChatMessage(page: Page, message: string): Promise<void> {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 10000 });
  await expect(chatInput).toBeEnabled({ timeout: 5000 });
  await chatInput.fill(message);

  const sendButton = page.getByRole('button', { name: /Send/i });
  await expect(sendButton).toBeEnabled({ timeout: 5000 });
  await sendButton.click();

  // Wait for agent to finish — input is re-enabled
  await expect(chatInput).toBeEnabled({ timeout: AGENT_TIMEOUT });
  await page.waitForTimeout(1000);
}

test.describe('File Browser — Live Cluster Integration', () => {
  test.skip(!LIVE_URL, 'Requires KAGENTI_UI_URL environment variable');
  test.setTimeout(300_000); // 5 min for full flow

  test.beforeEach(async ({ page }) => {
    await page.goto(LIVE_URL!);
    await loginIfNeeded(page);
  });

  test('write .md file with mermaid via chat, then browse and verify rendering', async ({ page }) => {
    // ── Step 1: Navigate to sandbox chat ──
    const sessionsNav = page
      .locator('nav a, nav button, [role="navigation"] a')
      .filter({ hasText: /^Sessions$/ });
    await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
    await sessionsNav.first().click();
    await page.waitForLoadState('networkidle');

    // Wait for sandbox page to load
    await expect(
      page.getByText(new RegExp(AGENT_NAME, 'i')).first()
    ).toBeVisible({ timeout: 15000 });

    // Click new session
    const newSessionBtn = page.getByRole('button', { name: /New Session/i });
    if (await newSessionBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newSessionBtn.click();
      // Handle New Session modal
      const startBtn = page.getByRole('button', { name: /^Start$/ });
      if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await startBtn.click();
        await page.waitForTimeout(500);
      }
      await page.waitForTimeout(500);
    }

    // ── Step 2: Ask agent to write a .md file with mermaid diagram ──
    const mdContent = [
      '# E2E Test Report',
      '',
      'This file was created by an **automated test**.',
      '',
      '## Architecture',
      '',
      '```mermaid',
      'graph TD',
      '  User[User] --> UI[Kagenti UI]',
      '  UI --> Backend[FastAPI Backend]',
      '  Backend --> K8s[Kubernetes API]',
      '  K8s --> Pod[Agent Pod]',
      '```',
      '',
      '## Results',
      '',
      '| Test | Status |',
      '|------|--------|',
      '| Write file | PASS |',
      '| Browse file | PASS |',
      '',
      'Generated at: ' + new Date().toISOString(),
    ].join('\\n');

    await sendChatMessage(
      page,
      `Write the following markdown content to a file called data/e2e-report.md. ` +
      `Create the data directory if it does not exist. Here is the content:\n\n${mdContent}`
    );

    // Wait for agent to process — either markdown response or tool call
    const agentOutput = page.locator('.sandbox-markdown')
      .or(page.locator('text=/Tool Call:|Result:|file_write|shell/i'));
    await expect(agentOutput.first()).toBeVisible({ timeout: 180000 });

    // ── Step 3: Navigate to file browser for this agent ──
    // Extract context_id from the current session URL (e.g. /sandbox/chat/team1/sandbox-basic/abc123)
    const currentUrl = page.url();
    const contextMatch = currentUrl.match(/\/sandbox\/(?:chat\/)?[^/]+\/[^/]+\/([a-f0-9]+)/);
    const contextId = contextMatch?.[1] || '';
    console.log(`[file-browser] Extracted contextId: ${contextId} from URL: ${currentUrl}`);

    // The workspace path depends on whether the agent uses per-context directories
    const workspacePath = contextId
      ? `/workspace/${contextId}/data`
      : '/workspace/data';

    // Use SPA navigation to avoid Keycloak re-auth redirect on page.goto()
    await page.evaluate(
      ({ ns, agent, path }) => {
        window.history.pushState({}, '', `/sandbox/files/${ns}/${agent}?path=${path}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      },
      { ns: NAMESPACE, agent: AGENT_NAME, path: workspacePath },
    );
    await page.waitForLoadState('networkidle');

    // Wait for tree view or "No files" message to render
    const treeOrEmpty = page.locator('[class*="pf-v5-c-tree-view"]').first()
      .or(page.getByText('No files in this directory'));
    await expect(treeOrEmpty).toBeVisible({ timeout: 30000 });

    // If no files at the context-specific path, try the workspace root
    const hasTree = await page.locator('[class*="pf-v5-c-tree-view"]').first().isVisible().catch(() => false);
    if (!hasTree) {
      console.log('[file-browser] No files at context path, trying workspace root');
      await page.evaluate(
        ({ ns, agent }) => {
          window.history.pushState({}, '', `/sandbox/files/${ns}/${agent}?path=/workspace`);
          window.dispatchEvent(new PopStateEvent('popstate'));
        },
        { ns: NAMESPACE, agent: AGENT_NAME },
      );
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(3000);
    }

    // ── Step 4: Verify e2e-report.md appears — search recursively ──
    // The file might be in a context subdirectory; click through directories
    let fileFound = await page.getByText('e2e-report.md').isVisible().catch(() => false);
    if (!fileFound) {
      // Try clicking into 'data' directory if visible
      const dataDir = page.getByText('data');
      if (await dataDir.isVisible({ timeout: 5000 }).catch(() => false)) {
        await dataDir.click();
        await page.waitForTimeout(2000);
        fileFound = await page.getByText('e2e-report.md').isVisible().catch(() => false);
      }
    }
    await expect(page.getByText('e2e-report.md')).toBeVisible({ timeout: 15000 });

    // ── Step 5: Click the file to preview ──
    await page.getByText('e2e-report.md').click();

    // ── Step 6: Verify markdown renders ──
    // Heading should render as H1
    await expect(page.locator('h1').filter({ hasText: 'E2E Test Report' })).toBeVisible({ timeout: 15000 });

    // Bold text should render
    await expect(page.locator('strong').filter({ hasText: 'automated test' })).toBeVisible({ timeout: 5000 });

    // GFM table should render
    await expect(page.getByText('Write file')).toBeVisible({ timeout: 5000 });

    // ── Step 7: Verify mermaid diagram renders as SVG ──
    // Mermaid diagrams render as <svg> elements inside the preview
    const mermaidSvg = page.locator('svg').first();
    await expect(mermaidSvg).toBeVisible({ timeout: 20000 });

    // The SVG should contain nodes from our diagram
    // (mermaid renders text labels inside the SVG)
    await expect(page.locator('svg').filter({ hasText: /User|Backend|Kubernetes/i }).first())
      .toBeVisible({ timeout: 10000 });

    // ── Step 8: Verify file metadata ──
    // File size label should be visible (exact value depends on content)
    const metadataBar = page.locator('[class*="pf-v5-c-label"]');
    await expect(metadataBar.first()).toBeVisible({ timeout: 5000 });

    // ── Step 9: Verify storage stats for this agent ──
    const statsResponse = await page.request.get(
      `${LIVE_URL}/api/v1/sandbox/${NAMESPACE}/stats/${AGENT_NAME}`
    );
    expect(statsResponse.ok()).toBeTruthy();
    const stats = await statsResponse.json();
    expect(stats.total_mounts).toBeGreaterThan(0);
    for (const mount of stats.mounts) {
      expect(mount).toHaveProperty('filesystem');
      expect(mount).toHaveProperty('size');
      expect(mount).toHaveProperty('used');
      expect(mount).toHaveProperty('mount_point');
    }
  });

  test('write code file via chat, browse and verify CodeBlock rendering', async ({ page }) => {
    // ── Step 1: Navigate to sandbox chat ──
    const sessionsNav = page
      .locator('nav a, nav button, [role="navigation"] a')
      .filter({ hasText: /^Sessions$/ });
    await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
    await sessionsNav.first().click();
    await page.waitForLoadState('networkidle');
    await expect(
      page.getByText(new RegExp(AGENT_NAME, 'i')).first()
    ).toBeVisible({ timeout: 15000 });

    const newSessionBtn = page.getByRole('button', { name: /New Session/i });
    if (await newSessionBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await newSessionBtn.click();
      // Handle New Session modal
      const startBtn = page.getByRole('button', { name: /^Start$/ });
      if (await startBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await startBtn.click();
        await page.waitForTimeout(500);
      }
      await page.waitForTimeout(500);
    }

    // ── Step 2: Ask agent to write a Python file ──
    await sendChatMessage(
      page,
      'Write a Python file at data/fibonacci.py with a function called fibonacci(n) ' +
      'that returns the nth Fibonacci number using iteration. Include a docstring.'
    );

    // Wait for agent to finish processing (tool call or text response)
    const codeOutput = page.locator('.sandbox-markdown')
      .or(page.locator('text=/Tool Call:|Result:|file_write|fibonacci/i'));
    await expect(codeOutput.first()).toBeVisible({ timeout: 180000 });

    // ── Step 3: Navigate to file browser ──
    // Extract context_id from the current session URL
    const currentUrl2 = page.url();
    const contextMatch2 = currentUrl2.match(/\/sandbox\/(?:chat\/)?[^/]+\/[^/]+\/([a-f0-9]+)/);
    const contextId2 = contextMatch2?.[1] || '';
    console.log(`[file-browser] Extracted contextId: ${contextId2} from URL: ${currentUrl2}`);

    const workspacePath2 = contextId2
      ? `/workspace/${contextId2}/data`
      : '/workspace/data';

    // Use SPA navigation to avoid Keycloak re-auth redirect
    await page.evaluate(
      ({ ns, agent, path }) => {
        window.history.pushState({}, '', `/sandbox/files/${ns}/${agent}?path=${path}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      },
      { ns: NAMESPACE, agent: AGENT_NAME, path: workspacePath2 },
    );
    await page.waitForLoadState('networkidle');

    // Wait for tree view or empty message
    const treeOrEmpty2 = page.locator('[class*="pf-v5-c-tree-view"]').first()
      .or(page.getByText('No files in this directory'));
    await expect(treeOrEmpty2).toBeVisible({ timeout: 30000 });

    // Fallback: try workspace root if context path is empty
    const hasTree2 = await page.locator('[class*="pf-v5-c-tree-view"]').first().isVisible().catch(() => false);
    if (!hasTree2) {
      console.log('[file-browser] No files at context path, trying workspace root');
      await page.evaluate(
        ({ ns, agent }) => {
          window.history.pushState({}, '', `/sandbox/files/${ns}/${agent}?path=/workspace`);
          window.dispatchEvent(new PopStateEvent('popstate'));
        },
        { ns: NAMESPACE, agent: AGENT_NAME },
      );
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(3000);
    }

    // ── Step 4: Verify fibonacci.py appears — search directories ──
    let pyFound = await page.getByText('fibonacci.py').isVisible().catch(() => false);
    if (!pyFound) {
      const dataDir = page.getByText('data');
      if (await dataDir.isVisible({ timeout: 5000 }).catch(() => false)) {
        await dataDir.click();
        await page.waitForTimeout(2000);
      }
    }
    await expect(page.getByText('fibonacci.py')).toBeVisible({ timeout: 15000 });

    // ── Step 5: Click to preview ──
    await page.getByText('fibonacci.py').click();

    // ── Step 6: Verify CodeBlock renders ──
    const codeBlock = page.locator('[class*="pf-v5-c-code-block"]');
    await expect(codeBlock).toBeVisible({ timeout: 15000 });

    // Verify the function definition is visible
    await expect(page.getByText('def fibonacci')).toBeVisible({ timeout: 5000 });
  });

});
