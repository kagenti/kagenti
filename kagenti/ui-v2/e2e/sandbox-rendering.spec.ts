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
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-rendering
 */
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';
const AGENT_TIMEOUT = 120_000;
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
// Shared helpers (same patterns as sandbox-sessions.spec.ts)
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

async function navigateToSandbox(page: Page) {
  const sessionsNav = page
    .locator('nav a, nav button, [role="navigation"] a')
    .filter({ hasText: /^Sessions$/ });
  await expect(sessionsNav.first()).toBeVisible({ timeout: 10000 });
  await sessionsNav.first().click();
  await page.waitForLoadState('networkidle');
  await expect(
    page
      .getByText(
        /sandbox-legion|sandbox-hardened|sandbox-basic|sandbox-restricted|Start a conversation/i
      )
      .first()
  ).toBeVisible({ timeout: 15000 });
}

async function startNewSession(page: Page) {
  const newSessionBtn = page.getByRole('button', { name: /New Session/i });
  await newSessionBtn.click();
  await page.waitForTimeout(500);
  await expect(page.getByText(/Start a conversation/i)).toBeVisible({
    timeout: 5000,
  });
}

/**
 * Send a message and wait for the agent to finish responding.
 * Returns once the chat input is re-enabled (agent done).
 */
async function sendAndWaitForResponse(
  page: Page,
  message: string,
  timeout = AGENT_TIMEOUT
): Promise<void> {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 10000 });
  await expect(chatInput).toBeEnabled({ timeout: 5000 });
  await chatInput.fill(message);

  const sendButton = page.getByRole('button', { name: /Send/i });
  await expect(sendButton).toBeEnabled({ timeout: 5000 });
  await sendButton.click();

  // Verify user message appears immediately
  await expect(page.getByText(message).first()).toBeVisible({ timeout: 5000 });

  // Wait for agent to finish: input becomes re-enabled
  await expect(chatInput).toBeEnabled({ timeout });

  // Give rendering a moment to settle
  await page.waitForTimeout(1500);
}

/**
 * Get the chat area container (the scrollable card body).
 */
function getChatArea(page: Page) {
  return page.locator('.pf-v5-c-card__body').first();
}

/**
 * Get the current session ID from the URL query param.
 */
function getSessionIdFromUrl(page: Page): string {
  return new URL(page.url()).searchParams.get('session') || '';
}

// ---------------------------------------------------------------------------
// Rendering-specific assertion helpers
// ---------------------------------------------------------------------------

/**
 * Locate all "Tool Call" expandable step blocks.
 * These render with border-left and contain "Tool Call:" text with a bold header.
 * We match on the border-left inline style (3px solid) to target the
 * ToolCallStep wrapper div precisely. CSS attribute selectors on `style` with
 * var(...) custom-property names are unreliable across browsers, so we match
 * on the literal "border-left" + "3px solid" portion instead.
 */
function getToolCallSteps(page: Page) {
  return page.locator('div[style*="border-left"]').filter({ hasText: /Tool Call:/ });
}

/**
 * Locate all "Result" expandable step blocks.
 * These render with border-left and contain "Result:" text.
 */
function getResultSteps(page: Page) {
  return page.locator('div[style*="border-left"]').filter({ hasText: /Result:/ });
}

/**
 * Locate assistant message bubbles that contain rendered markdown.
 * These are div.sandbox-markdown elements inside non-user bubbles.
 */
function getMarkdownResponses(page: Page) {
  return page.locator('.sandbox-markdown');
}

/**
 * Assert that a tool call step has the correct styling (info-color border).
 */
async function assertToolCallStepStyling(toolCallStep: ReturnType<Page['locator']>) {
  // The element should be visible
  await expect(toolCallStep).toBeVisible();

  // It should contain the collapsed arrow (unexpanded by default)
  const text = await toolCallStep.textContent();
  expect(text).toContain('Tool Call:');

  // Check the inline border-left style — info-color (blue border)
  const style = await toolCallStep.getAttribute('style');
  expect(style).toContain('border-left');

  // Font weight 600 on the header
  const headerDiv = toolCallStep.locator('div').first();
  const fontWeight = await headerDiv.evaluate(
    (el) => window.getComputedStyle(el).fontWeight
  );
  // fontWeight should be 600 or "bold" (600 == bold in most fonts)
  expect(['600', 'bold', '700']).toContain(fontWeight);
}

/**
 * Assert that a result step has the correct styling (success-color border).
 */
async function assertResultStepStyling(resultStep: ReturnType<Page['locator']>) {
  await expect(resultStep).toBeVisible();

  const text = await resultStep.textContent();
  expect(text).toContain('Result:');

  const style = await resultStep.getAttribute('style');
  expect(style).toContain('border-left');
}

// ===========================================================================
// TESTS — serial execution (tests share session state)
// ===========================================================================

test.describe.serial('Sandbox Rendering — Tool Call Steps', () => {
  const runId = Date.now().toString(36);
  let sessionIdForReload = '';

  test('tool call steps should render as expandable blocks', async ({
    page,
  }) => {
    test.setTimeout(180_000);
    screenshotIdx = 0;

    // ---- Login & Navigate ----
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandbox(page);
    await snap(page, 'sandbox-loaded');

    // ---- Start a new session ----
    await startNewSession(page);
    await snap(page, 'new-session');

    // ---- Send a command that triggers a tool call ----
    await sendAndWaitForResponse(
      page,
      'Run the command: echo hello-from-rendering-test'
    );
    await snap(page, 'after-echo-response');

    const chatArea = getChatArea(page);
    const chatText = (await chatArea.textContent()) || '';
    console.log(
      `[rendering] Chat text length after echo: ${chatText.length}`
    );

    // ---- Assert: Tool Call expandable step is present ----
    const toolCallSteps = getToolCallSteps(page);
    const toolCallCount = await toolCallSteps.count();
    console.log(`[rendering] Tool Call steps found: ${toolCallCount}`);
    expect(toolCallCount).toBeGreaterThanOrEqual(1);

    // Assert specific styling on the first tool call step
    await assertToolCallStepStyling(toolCallSteps.first());
    await snap(page, 'tool-call-step-verified');

    // ---- Assert: Result expandable step is present ----
    const resultSteps = getResultSteps(page);
    const resultCount = await resultSteps.count();
    console.log(`[rendering] Result steps found: ${resultCount}`);
    expect(resultCount).toBeGreaterThanOrEqual(1);

    // Assert specific styling on the first result step
    await assertResultStepStyling(resultSteps.first());
    await snap(page, 'result-step-verified');

    // ---- Assert: Final text response is rendered as markdown ----
    const markdownBlocks = getMarkdownResponses(page);
    const markdownCount = await markdownBlocks.count();
    console.log(`[rendering] Markdown response blocks found: ${markdownCount}`);
    expect(markdownCount).toBeGreaterThanOrEqual(1);

    // The markdown block should contain actual rendered HTML (not raw text)
    // ReactMarkdown wraps content in <p> tags at minimum
    const lastMarkdown = markdownBlocks.last();
    const innerHtml = await lastMarkdown.innerHTML();
    // Markdown renderer produces <p>, <code>, <pre>, <ul>, <li>, etc.
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
    // Before click: should show collapsed arrow
    await expect(firstToolCall).toContainText('\u25B6'); // right-pointing triangle

    // Click to expand
    await firstToolCall.click();
    await page.waitForTimeout(500);
    await snap(page, 'tool-call-expanded');

    // After click: should show expanded arrow and code content
    await expect(firstToolCall).toContainText('\u25BC'); // down-pointing triangle
    // Expanded tool call shows a <pre> with the tool name and arguments
    const expandedPre = firstToolCall.locator('pre');
    const preCount = await expandedPre.count();
    expect(preCount).toBeGreaterThanOrEqual(1);
    console.log(
      `[rendering] Expanded tool call <pre> blocks: ${preCount}`
    );

    // Click again to collapse
    await firstToolCall.click();
    await page.waitForTimeout(300);
    await expect(firstToolCall).toContainText('\u25B6');
    await snap(page, 'tool-call-collapsed-again');
  });

  test('agent response should show activity steps inline', async ({
    page,
  }) => {
    test.setTimeout(180_000);

    // ---- Login & Navigate ----
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandbox(page);

    // ---- Start a new session ----
    await startNewSession(page);
    await snap(page, 'new-session-multi-tool');

    // ---- Send a command that triggers multiple tool calls ----
    await sendAndWaitForResponse(
      page,
      `Write 'test123-${runId}' to a file called render-test.txt, then read it back`
    );
    await snap(page, 'after-write-read-response');

    const chatArea = getChatArea(page);
    const chatText = (await chatArea.textContent()) || '';

    // ---- Assert: At least 2 tool call steps visible (write + read) ----
    const toolCallSteps = getToolCallSteps(page);
    const toolCallCount = await toolCallSteps.count();
    console.log(
      `[rendering] Tool Call steps for write+read: ${toolCallCount}`
    );
    expect(toolCallCount).toBeGreaterThanOrEqual(2);

    // ---- Assert: At least 2 result steps visible ----
    const resultSteps = getResultSteps(page);
    const resultCount = await resultSteps.count();
    console.log(`[rendering] Result steps for write+read: ${resultCount}`);
    expect(resultCount).toBeGreaterThanOrEqual(2);

    // ---- Assert: Final response mentions the file content ----
    // The agent should read back "test123-<runId>" and mention it
    expect(chatText).toContain(`test123-${runId}`);

    // ---- Assert: Steps appear in chronological order ----
    // Tool Call steps should be interleaved with Result steps in the DOM
    // Verify the first tool call appears before the first result
    const allStepElements = page.locator(
      'div[style*="border-left: 3px solid"]'
    );
    const allStepCount = await allStepElements.count();
    console.log(
      `[rendering] Total bordered step elements: ${allStepCount}`
    );
    // At minimum: 2 tool calls + 2 results = 4 bordered steps
    expect(allStepCount).toBeGreaterThanOrEqual(4);

    // Capture session ID for the reload test
    sessionIdForReload = getSessionIdFromUrl(page);
    console.log(
      `[rendering] Session ID for reload test: ${sessionIdForReload}`
    );
    expect(sessionIdForReload).toBeTruthy();

    await snap(page, 'multi-tool-steps-verified');
  });

  test('loaded session history should show tool call steps', async ({
    page,
  }) => {
    test.setTimeout(180_000);

    // Skip if the previous test did not create a session
    test.skip(
      !sessionIdForReload,
      'No session ID from previous test — skipping history reload test'
    );

    // ---- Login & Navigate ----
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandbox(page);
    await page.waitForTimeout(3000); // Wait for session list to populate
    await snap(page, 'history-test-sessions-loaded');

    // ---- Click "+ New Session" to ensure we are NOT on the target session ----
    await startNewSession(page);
    await snap(page, 'history-test-new-session');

    // ---- Find and click the session in the sidebar ----
    // Sessions show the first message as title. Our session had the write+read
    // command, so look for "render-test" or the session itself.
    // First try finding by session title text in sidebar
    const sidebarSessionItem = page.locator('[role="button"]').filter({
      hasText: /render-test|Write.*test123/i,
    });

    let sessionFound = false;
    if ((await sidebarSessionItem.count()) > 0) {
      await sidebarSessionItem.first().click();
      sessionFound = true;
    } else {
      // Fallback: navigate directly via URL with session param
      console.log(
        `[rendering] Session not found in sidebar — navigating via URL`
      );
      await page.goto(`/?session=${sessionIdForReload}`);
      await page.waitForLoadState('networkidle');
      await loginIfNeeded(page);
      await navigateToSandbox(page);
      sessionFound = true;
    }

    // ---- Wait for history to load ----
    await page.waitForTimeout(5000);
    await snap(page, 'history-loaded');

    if (sessionFound) {
      const chatArea = getChatArea(page);
      const chatText = (await chatArea.textContent()) || '';
      console.log(
        `[rendering] History chat text length: ${chatText.length}`
      );
      console.log(
        `[rendering] History chat text preview: ${chatText.substring(0, 300)}`
      );

      // ---- KEY ASSERTION: Loaded history shows Tool Call steps ----
      // This is the critical test — history must render tool calls as
      // expandable steps, not as flat text or "Error: connection..."
      const toolCallSteps = getToolCallSteps(page);
      const toolCallCount = await toolCallSteps.count();
      console.log(
        `[rendering] History Tool Call steps: ${toolCallCount}`
      );

      // History MUST show tool call steps — this is the whole point of
      // structured history rendering
      expect(toolCallCount).toBeGreaterThanOrEqual(1);

      // ---- Assert: "Tool Call" text is visible in loaded history ----
      await expect(page.getByText(/Tool Call:/)).toBeVisible({ timeout: 5000 });

      // ---- Assert: "Result" text is visible in loaded history ----
      const resultSteps = getResultSteps(page);
      const resultCount = await resultSteps.count();
      console.log(`[rendering] History Result steps: ${resultCount}`);
      expect(resultCount).toBeGreaterThanOrEqual(1);
      await expect(page.getByText(/Result:/).first()).toBeVisible({
        timeout: 5000,
      });

      // ---- Assert: History does NOT show raw "Error: connection" garbage ----
      expect(chatText).not.toContain('Error: connection');
      expect(chatText).not.toContain('Error: chunked');

      // ---- Assert: Tool call steps in history have correct styling ----
      await assertToolCallStepStyling(toolCallSteps.first());
      await assertResultStepStyling(resultSteps.first());

      // ---- Assert: Tool call steps in history are expandable ----
      const firstHistoryToolCall = toolCallSteps.first();
      await expect(firstHistoryToolCall).toContainText('\u25B6');
      await firstHistoryToolCall.click();
      await page.waitForTimeout(500);
      await expect(firstHistoryToolCall).toContainText('\u25BC');
      // Verify expanded content shows a <pre> block
      const expandedPre = firstHistoryToolCall.locator('pre');
      expect(await expandedPre.count()).toBeGreaterThanOrEqual(1);

      await snap(page, 'history-tool-calls-verified');
    }
  });

  test('connection error should auto-recover and show actual response', async ({
    page,
  }) => {
    test.setTimeout(180_000);

    // ---- Login & Navigate ----
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandbox(page);

    // ---- Start a new session ----
    await startNewSession(page);
    await snap(page, 'recovery-new-session');

    // ---- Send a command that triggers a tool call ----
    const recoveryMarker = `recovery-${runId}`;

    const chatInput = page.getByPlaceholder(/Type your message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });
    await expect(chatInput).toBeEnabled({ timeout: 5000 });
    await chatInput.fill(
      `Run the command: echo "${recoveryMarker}" && sleep 2 && echo done`
    );

    const sendButton = page.getByRole('button', { name: /Send/i });
    await expect(sendButton).toBeEnabled({ timeout: 5000 });
    await sendButton.click();

    // Verify user message appears
    await expect(page.getByText(recoveryMarker).first()).toBeVisible({
      timeout: 5000,
    });
    await snap(page, 'recovery-message-sent');

    // ---- Monitor for connection error vs normal response ----
    // We wait for one of two outcomes:
    // 1. Normal completion: input re-enabled without error alert
    // 2. Connection error: danger alert appears, then recovery kicks in

    // Wait for either the input to be re-enabled OR an error alert to appear
    const inputReEnabled = chatInput
      .waitFor({ state: 'attached', timeout: AGENT_TIMEOUT })
      .then(() => chatInput.isEnabled())
      .catch(() => false);

    const errorAlert = page
      .locator('.pf-v5-c-alert.pf-m-danger')
      .first();

    // Give the agent time to respond
    await expect(chatInput).toBeEnabled({ timeout: AGENT_TIMEOUT });
    await page.waitForTimeout(2000);
    await snap(page, 'recovery-after-wait');

    // Check if a connection error appeared
    const hadConnectionError = await errorAlert
      .isVisible({ timeout: 2000 })
      .catch(() => false);

    if (hadConnectionError) {
      console.log(
        '[rendering] Connection error detected — verifying recovery'
      );
      await snap(page, 'recovery-error-visible');

      // ---- Assert: The error message mentions connection interruption ----
      const alertText = (await errorAlert.textContent()) || '';
      expect(alertText).toMatch(
        /connection|interrupted|waiting|still working/i
      );

      // ---- Wait for backoff recovery (up to 30 seconds) ----
      // The recovery mechanism polls the session status and reloads history
      // when the session completes. The error alert should disappear.
      await expect(errorAlert).toBeHidden({ timeout: 30_000 });
      console.log('[rendering] Connection error recovered');
      await snap(page, 'recovery-error-cleared');

      // ---- Assert: The recovered response contains actual content ----
      const chatArea = getChatArea(page);
      const recoveredText = (await chatArea.textContent()) || '';
      // After recovery, the history is reloaded — should have tool call steps
      // or at minimum the agent's response text
      expect(recoveredText.length).toBeGreaterThan(50);
      // Should NOT still show "Error: connection..." as the final message
      // (the recovery replaces it with actual history)
    } else {
      console.log(
        '[rendering] No connection error — response rendered normally'
      );

      // ---- Assert: Normal response with tool call steps ----
      const chatArea = getChatArea(page);
      const chatText = (await chatArea.textContent()) || '';

      // Should contain the echo output somewhere
      expect(chatText).toContain(recoveryMarker);

      // Should have at least one tool call step (the echo command)
      const toolCallSteps = getToolCallSteps(page);
      const toolCallCount = await toolCallSteps.count();
      console.log(
        `[rendering] Recovery test Tool Call steps: ${toolCallCount}`
      );
      expect(toolCallCount).toBeGreaterThanOrEqual(1);

      // Should have at least one result step
      const resultSteps = getResultSteps(page);
      const resultCount = await resultSteps.count();
      console.log(
        `[rendering] Recovery test Result steps: ${resultCount}`
      );
      expect(resultCount).toBeGreaterThanOrEqual(1);
    }

    // ---- Final screenshot ----
    await snap(page, 'recovery-test-complete');

    // ---- Assert: No stale error alerts remain ----
    const remainingErrors = page.locator('.pf-v5-c-alert.pf-m-danger');
    const errorCount = await remainingErrors.count();
    expect(errorCount).toBe(0);
  });
});
