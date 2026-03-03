/**
 * Sandbox Rendering E2E Tests
 *
 * Assertive tests verifying how multi-turn conversations with tool calls
 * render in the sandbox chat. Tests the EXACT visual output:
 * - Tool Call expandable blocks with info-color border
 * - Result expandable blocks with success-color border
 * - Final LLM responses rendered as markdown (not raw text)
 * - Session history preserving tool call rendering
 * - Connection error recovery via backoff polling
 *
 * All API calls are mocked — no cluster or running agent required.
 * The SandboxPage SSE streaming handler detects tool_call / tool_result
 * events inside data.event.message and renders them as ToolCallStep cards.
 *
 * Run: npx playwright test sandbox-rendering
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';
const SCREENSHOT_DIR = 'test-results/sandbox-rendering';

let screenshotIdx = 0;
async function snap(page: Page, label: string) {
  screenshotIdx++;
  const name = `${String(screenshotIdx).padStart(2, '0')}-${label}`;
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
  console.log(`[rendering] Screenshot: ${name}`);
}

// ---------------------------------------------------------------------------
// Auth helper — same as sandbox-delegation.spec.ts
// ---------------------------------------------------------------------------

async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 30000 });

  const isKeycloakLogin = await page
    .locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);

  if (!isKeycloakLogin) {
    const signInButton = page.getByRole('button', { name: /Sign In/i });
    const hasSignIn = await signInButton
      .isVisible({ timeout: 5000 })
      .catch(() => false);
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

  if (page.url().includes('VERIFY_PROFILE')) {
    const verifySubmit = page.locator(
      'input[type="submit"], button[type="submit"]'
    );
    if (await verifySubmit.isVisible({ timeout: 2000 }).catch(() => false)) {
      await verifySubmit.click();
      await page.waitForURL(/^(?!.*keycloak)/, { timeout: 15000 });
    }
  }
}

/** Navigate to the Sessions (sandbox chat) page. */
async function navigateToSandboxChat(page: Page) {
  await page.locator('nav a', { hasText: 'Sessions' }).first().click();
  await page.waitForLoadState('networkidle');
  await expect(
    page
      .locator(
        'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
      )
      .first()
  ).toBeVisible({ timeout: 15000 });
}

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

/** Wrap an object as a single SSE data line. */
function sseEvent(data: Record<string, unknown>): string {
  return `data: ${JSON.stringify(data)}\n\n`;
}

/** Build an SSE line whose event.message contains graph-event JSON lines.
 *  parseGraphEvent() in SandboxPage.tsx parses each line as JSON and looks for
 *  type === 'tool_call' | 'tool_result' | 'llm_response'. */
function graphEventsLine(
  sessionId: string,
  ...events: Record<string, unknown>[]
): string {
  const message = events.map((e) => JSON.stringify(e)).join('\n');
  return sseEvent({
    session_id: sessionId,
    event: {
      type: 'status',
      taskId: 'task-1',
      state: 'WORKING',
      final: false,
      message,
    },
  });
}

function doneEvent(sessionId: string, content?: string): string {
  const payload: Record<string, unknown> = { done: true, session_id: sessionId };
  if (content) payload.content = content;
  return sseEvent(payload);
}

// ---------------------------------------------------------------------------
// Rendering-specific assertion helpers
// ---------------------------------------------------------------------------

/**
 * Locate all "Tool Call" expandable step blocks.
 * ToolCallStep renders with inline borderLeft (React converts to border-left)
 * and contains "Tool Call:" text.
 */
function getToolCallSteps(page: Page) {
  return page
    .locator('div[style*="border-left"]')
    .filter({ hasText: /Tool Call:/ });
}

/**
 * Locate all "Result" expandable step blocks.
 */
function getResultSteps(page: Page) {
  return page
    .locator('div[style*="border-left"]')
    .filter({ hasText: /Result:/ });
}

/**
 * Locate assistant message bubbles containing rendered markdown.
 */
function getMarkdownResponses(page: Page) {
  return page.locator('.sandbox-markdown');
}

/**
 * Assert that a tool call step has the correct styling (info-color border).
 */
async function assertToolCallStepStyling(
  toolCallStep: ReturnType<Page['locator']>
) {
  await expect(toolCallStep).toBeVisible();

  const text = await toolCallStep.textContent();
  expect(text).toContain('Tool Call:');

  const style = await toolCallStep.getAttribute('style');
  expect(style).toContain('border-left');

  // Font weight 600 on the header div
  const headerDiv = toolCallStep.locator('div').first();
  const fontWeight = await headerDiv.evaluate(
    (el) => window.getComputedStyle(el).fontWeight
  );
  expect(['600', 'bold', '700']).toContain(fontWeight);
}

/**
 * Assert that a result step has the correct styling (success-color border).
 */
async function assertResultStepStyling(
  resultStep: ReturnType<Page['locator']>
) {
  await expect(resultStep).toBeVisible();
  const text = await resultStep.textContent();
  expect(text).toContain('Result:');
  const style = await resultStep.getAttribute('style');
  expect(style).toContain('border-left');
}

// ===========================================================================
// TESTS
// ===========================================================================

test.describe('Sandbox Rendering — Tool Call Steps (mocked)', () => {
  test.setTimeout(120_000);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
  });

  // -----------------------------------------------------------------------
  // Test 1: single tool call renders as expandable block
  // -----------------------------------------------------------------------
  test('tool call steps should render as expandable blocks', async ({
    page,
  }) => {
    screenshotIdx = 0;

    await navigateToSandboxChat(page);
    await snap(page, 'sandbox-loaded');

    // Mock SSE: one tool_call, one tool_result, then final content + done
    const sessionId = 'render-test-session-1';
    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const body = [
        // Tool call event
        graphEventsLine(sessionId, {
          type: 'tool_call',
          tools: [{ name: 'bash', args: { command: 'echo hello-from-rendering-test' } }],
        }),
        // Tool result event
        graphEventsLine(sessionId, {
          type: 'tool_result',
          name: 'bash',
          output: 'hello-from-rendering-test',
        }),
        // Final content (markdown)
        sseEvent({
          session_id: sessionId,
          content: 'The command executed successfully. Output: `hello-from-rendering-test`',
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    // Send a message
    const chatInput = page
      .locator('textarea[aria-label="Message input"]')
      .first();
    await chatInput.fill('Run the command: echo hello-from-rendering-test');
    await page.getByRole('button', { name: /Send/i }).click();
    await snap(page, 'after-echo-response');

    // ---- Assert: Tool Call expandable step is present ----
    const toolCallSteps = getToolCallSteps(page);
    await expect(toolCallSteps.first()).toBeVisible({ timeout: 15000 });
    const toolCallCount = await toolCallSteps.count();
    console.log(`[rendering] Tool Call steps found: ${toolCallCount}`);
    expect(toolCallCount).toBeGreaterThanOrEqual(1);

    // Assert specific styling
    await assertToolCallStepStyling(toolCallSteps.first());
    await snap(page, 'tool-call-step-verified');

    // ---- Assert: Result expandable step is present ----
    const resultSteps = getResultSteps(page);
    await expect(resultSteps.first()).toBeVisible({ timeout: 15000 });
    const resultCount = await resultSteps.count();
    console.log(`[rendering] Result steps found: ${resultCount}`);
    expect(resultCount).toBeGreaterThanOrEqual(1);

    await assertResultStepStyling(resultSteps.first());
    await snap(page, 'result-step-verified');

    // ---- Assert: Final text response is rendered as markdown ----
    const markdownBlocks = getMarkdownResponses(page);
    const markdownCount = await markdownBlocks.count();
    console.log(
      `[rendering] Markdown response blocks found: ${markdownCount}`
    );
    expect(markdownCount).toBeGreaterThanOrEqual(1);

    // ReactMarkdown wraps content in <p>, <code>, etc.
    const lastMarkdown = markdownBlocks.last();
    const innerHtml = await lastMarkdown.innerHTML();
    const hasRenderedHtml =
      innerHtml.includes('<p>') ||
      innerHtml.includes('<code>') ||
      innerHtml.includes('<pre>') ||
      innerHtml.includes('<ul>') ||
      innerHtml.includes('<li>');
    expect(hasRenderedHtml).toBe(true);
    console.log(
      `[rendering] Markdown inner HTML preview: ${innerHtml.substring(0, 200)}`
    );
    await snap(page, 'markdown-rendering-verified');

    // ---- Assert: Tool call step is expandable (click to expand) ----
    const firstToolCall = toolCallSteps.first();
    await expect(firstToolCall).toContainText('\u25B6'); // collapsed arrow

    await firstToolCall.click();
    await page.waitForTimeout(500);
    await snap(page, 'tool-call-expanded');

    await expect(firstToolCall).toContainText('\u25BC'); // expanded arrow
    const expandedPre = firstToolCall.locator('pre');
    expect(await expandedPre.count()).toBeGreaterThanOrEqual(1);
    console.log(
      `[rendering] Expanded tool call <pre> blocks: ${await expandedPre.count()}`
    );

    // Click again to collapse
    await firstToolCall.click();
    await page.waitForTimeout(300);
    await expect(firstToolCall).toContainText('\u25B6');
    await snap(page, 'tool-call-collapsed-again');
  });

  // -----------------------------------------------------------------------
  // Test 2: multiple tool call steps rendered inline
  // -----------------------------------------------------------------------
  test('agent response should show activity steps inline', async ({
    page,
  }) => {
    await navigateToSandboxChat(page);

    const sessionId = 'render-test-session-2';
    const runId = Date.now().toString(36);

    await page.route('**/api/v1/sandbox/**/chat/stream', async (route) => {
      const body = [
        // First tool call — write file
        graphEventsLine(sessionId, {
          type: 'tool_call',
          tools: [
            {
              name: 'write_file',
              args: { path: 'render-test.txt', content: `test123-${runId}` },
            },
          ],
        }),
        graphEventsLine(sessionId, {
          type: 'tool_result',
          name: 'write_file',
          output: 'File written successfully',
        }),
        // Second tool call — read file
        graphEventsLine(sessionId, {
          type: 'tool_call',
          tools: [{ name: 'read_file', args: { path: 'render-test.txt' } }],
        }),
        graphEventsLine(sessionId, {
          type: 'tool_result',
          name: 'read_file',
          output: `test123-${runId}`,
        }),
        // Final content
        sseEvent({
          session_id: sessionId,
          content: `I wrote \`test123-${runId}\` to render-test.txt and read it back. The content matches.`,
        }),
        doneEvent(sessionId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache', Connection: 'keep-alive' },
        body: body.join(''),
      });
    });

    const chatInput = page
      .locator('textarea[aria-label="Message input"]')
      .first();
    await chatInput.fill(
      `Write 'test123-${runId}' to render-test.txt, then read it back`
    );
    await page.getByRole('button', { name: /Send/i }).click();
    await snap(page, 'after-write-read-response');

    // ---- Assert: At least 2 tool call steps (write + read) ----
    const toolCallSteps = getToolCallSteps(page);
    await expect(toolCallSteps.first()).toBeVisible({ timeout: 15000 });
    const toolCallCount = await toolCallSteps.count();
    console.log(
      `[rendering] Tool Call steps for write+read: ${toolCallCount}`
    );
    expect(toolCallCount).toBeGreaterThanOrEqual(2);

    // ---- Assert: At least 2 result steps ----
    const resultSteps = getResultSteps(page);
    const resultCount = await resultSteps.count();
    console.log(`[rendering] Result steps for write+read: ${resultCount}`);
    expect(resultCount).toBeGreaterThanOrEqual(2);

    // ---- Assert: Final response mentions the file content ----
    const chatArea = page.locator('.pf-v5-c-card__body').first();
    const chatText = (await chatArea.textContent()) || '';
    expect(chatText).toContain(`test123-${runId}`);

    // ---- Assert: Total bordered step elements ----
    const allStepElements = page.locator(
      'div[style*="border-left"]'
    ).filter({ hasText: /Tool Call:|Result:/ });
    const allStepCount = await allStepElements.count();
    console.log(
      `[rendering] Total bordered step elements: ${allStepCount}`
    );
    expect(allStepCount).toBeGreaterThanOrEqual(4);

    await snap(page, 'multi-tool-steps-verified');
  });

  // -----------------------------------------------------------------------
  // Test 3: session history renders tool call steps from history endpoint
  // -----------------------------------------------------------------------
  test('loaded session history should show tool call steps', async ({
    page,
  }) => {
    const historySessionId = 'render-test-history-session';

    // Mock the history endpoint to return messages with tool_call / tool_result parts
    await page.route('**/api/v1/sandbox/**/history*', async (route) => {
      const url = route.request().url();
      // Only mock for our test session
      if (!url.includes(historySessionId)) {
        return route.fallback();
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          messages: [
            {
              role: 'user',
              _index: 0,
              parts: [{ kind: 'text', text: 'Run echo hello' }],
            },
            {
              role: 'assistant',
              _index: 1,
              parts: [
                {
                  kind: 'data',
                  type: 'tool_call',
                  tools: [
                    { name: 'bash', args: { command: 'echo hello' } },
                  ],
                },
              ],
            },
            {
              role: 'assistant',
              _index: 2,
              parts: [
                {
                  kind: 'data',
                  type: 'tool_result',
                  name: 'bash',
                  output: 'hello',
                },
              ],
            },
            {
              role: 'assistant',
              _index: 3,
              parts: [{ kind: 'text', text: 'The command output `hello`.' }],
            },
          ],
          has_more: false,
          total: 4,
        }),
      });
    });

    // Mock sessions list to include our history session
    await page.route('**/api/v1/sandbox/**/sessions?**', async (route) => {
      const url = route.request().url();
      if (url.includes('/sessions?') || url.endsWith('/sessions')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                context_id: historySessionId,
                status: { state: 'completed' },
                metadata: { title: 'Run echo hello' },
                created_at: new Date().toISOString(),
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          }),
        });
      }
      return route.fallback();
    });

    await navigateToSandboxChat(page);

    // Navigate to the history session via URL
    await page.goto(`/sandbox?session=${historySessionId}`);
    await page.waitForTimeout(3000);
    await snap(page, 'history-loaded');

    // ---- Assert: Tool Call steps rendered from history ----
    const toolCallSteps = getToolCallSteps(page);
    await expect(toolCallSteps.first()).toBeVisible({ timeout: 15000 });
    const toolCallCount = await toolCallSteps.count();
    console.log(`[rendering] History Tool Call steps: ${toolCallCount}`);
    expect(toolCallCount).toBeGreaterThanOrEqual(1);

    await expect(page.getByText(/Tool Call:/).first()).toBeVisible({
      timeout: 5000,
    });

    // ---- Assert: Result steps rendered from history ----
    const resultSteps = getResultSteps(page);
    const resultCount = await resultSteps.count();
    console.log(`[rendering] History Result steps: ${resultCount}`);
    expect(resultCount).toBeGreaterThanOrEqual(1);
    await expect(page.getByText(/Result:/).first()).toBeVisible({
      timeout: 5000,
    });

    // ---- Assert: No error garbage ----
    const chatArea = page.locator('.pf-v5-c-card__body').first();
    const chatText = (await chatArea.textContent()) || '';
    expect(chatText).not.toContain('Error: connection');
    expect(chatText).not.toContain('Error: chunked');

    // ---- Assert: Correct styling ----
    await assertToolCallStepStyling(toolCallSteps.first());
    await assertResultStepStyling(resultSteps.first());

    // ---- Assert: Expandable ----
    const firstHistoryToolCall = toolCallSteps.first();
    await expect(firstHistoryToolCall).toContainText('\u25B6');
    await firstHistoryToolCall.click();
    await page.waitForTimeout(500);
    await expect(firstHistoryToolCall).toContainText('\u25BC');
    const expandedPre = firstHistoryToolCall.locator('pre');
    expect(await expandedPre.count()).toBeGreaterThanOrEqual(1);

    await snap(page, 'history-tool-calls-verified');
  });
});
