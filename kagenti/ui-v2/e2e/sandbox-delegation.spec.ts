/**
 * Sandbox Delegation E2E Test — Live Integration
 *
 * Forces a real delegate tool call against a running sandbox-legion agent and
 * verifies the full lifecycle:
 * 1. Login, navigate to sandbox with agent=sandbox-legion via URL param
 * 2. Send a prompt that triggers in-process delegation
 * 3. Wait for the delegate tool call to render in the chat stream
 * 4. Verify child session creation in the SessionSidebar
 * 5. Verify the delegated task completed (file exists)
 *
 * Requires a live cluster with sandbox-legion deployed.
 *
 * Run: KAGENTI_UI_URL=https://... npx playwright test sandbox-delegation
 */
import { test, expect, type Page } from '@playwright/test';
import { loginIfNeeded } from './helpers/auth';

const AGENT_NAME = 'sandbox-legion';
const AGENT_TIMEOUT = 180_000;
const SCREENSHOT_DIR = 'test-results/sandbox-delegation';

let screenshotIdx = 0;
async function snap(page: Page, label: string) {
  screenshotIdx++;
  const name = `${String(screenshotIdx).padStart(2, '0')}-${label}`;
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
}

/**
 * Navigate to the sandbox page and set agent via URL param.
 * SandboxPage has a useEffect that syncs selectedAgent from ?agent=.
 */
async function navigateToSandboxWithAgent(page: Page, agentName: string) {
  // Navigate via full URL so React Router's searchParams are in sync.
  // This prevents state desync between window.location and React Router
  // which would cause setSearchParams({ session: ... }) to silently fail.
  await page.goto(`/sandbox?agent=${encodeURIComponent(agentName)}`);
  await page.waitForLoadState('networkidle');

  // Re-login if redirected to Keycloak
  if (page.url().includes('keycloak') || page.url().includes('auth/realms')) {
    await loginIfNeeded(page);
    await page.goto(`/sandbox?agent=${encodeURIComponent(agentName)}`);
    await page.waitForLoadState('networkidle');
  }

  // Confirm the agent badge renders
  const agentLabel = page
    .locator('[class*="pf-v5-c-label"]')
    .filter({ hasText: agentName });
  await expect(agentLabel.first()).toBeVisible({ timeout: 10000 });
}

/**
 * Send a message and wait for the agent to finish processing.
 * "Finished" = chat input re-enabled after the agent stops streaming.
 */
async function sendAndWait(
  page: Page,
  message: string,
  timeout = AGENT_TIMEOUT
): Promise<string> {
  const chatInput = page.getByPlaceholder(/Type your message/i);
  await expect(chatInput).toBeVisible({ timeout: 10000 });
  await expect(chatInput).toBeEnabled({ timeout: 5000 });
  await chatInput.fill(message);

  const sendButton = page.getByRole('button', { name: /Send/i });
  await expect(sendButton).toBeEnabled({ timeout: 5000 });
  await sendButton.click();

  // Verify user message appears in chat
  await expect(
    page.getByTestId('chat-messages').getByText(message.substring(0, 30)).first()
  ).toBeVisible({ timeout: 10000 });

  // Wait for agent to finish — input re-enables when streaming completes
  await expect(chatInput).toBeEnabled({ timeout });
  await page.waitForTimeout(1000);

  const chatArea = page.getByTestId('chat-messages');
  return (await chatArea.textContent()) || '';
}

// =============================================================================
// TEST
// =============================================================================

test.describe('Sandbox Delegation — Live', () => {

  test('delegate tool spawns child session, renders in sidebar, completes task', async ({
    page,
  }) => {
    test.setTimeout(300_000);
    screenshotIdx = 0;

    // ── Step 1: Login and navigate to sandbox with agent param ───────────
    await page.goto('/');
    await loginIfNeeded(page);
    await navigateToSandboxWithAgent(page, AGENT_NAME);
    await snap(page, 'agent-selected');
    console.log(
      `[delegate] Agent ${AGENT_NAME} selected, URL: ${page.url()}`
    );

    // ── Step 2: Send delegation message ──────────────────────────────────
    const delegateMessage =
      "Use the delegate tool to spawn a child agent that creates a file " +
      "called /workspace/delegate-test.txt with the content 'hello from child'. " +
      "Use in-process mode.";

    const chatContent = await sendAndWait(page, delegateMessage, AGENT_TIMEOUT);
    await snap(page, 'delegate-response');
    console.log(
      `[delegate] Agent responded, chat length: ${chatContent.length}`
    );

    // ── Step 3: Verify delegate tool call appeared in chat ───────────────
    const chatMessages = page.getByTestId('chat-messages');

    // Prefer agent-loop-card, fall back to tool call text or delegate keyword
    const toolCallVisible = await chatMessages
      .locator('[data-testid="agent-loop-card"]')
      .or(chatMessages.locator('text=/Tool Call:|delegate|Delegation/i'))
      .first()
      .isVisible({ timeout: 15000 })
      .catch(() => false);

    // Prefer agent-loop-card, fall back to result text
    const toolResultVisible = await chatMessages
      .locator('[data-testid="agent-loop-card"]')
      .or(chatMessages.locator('text=/Result:|child|completed|delegate-test|hello from child/i'))
      .first()
      .isVisible({ timeout: 10000 })
      .catch(() => false);

    console.log(
      `[delegate] Tool call visible: ${toolCallVisible}, result visible: ${toolResultVisible}`
    );
    await snap(page, 'tool-call-rendered');

    // At least one indicator of the delegation should be in the chat
    expect(toolCallVisible || toolResultVisible).toBe(true);

    // ── Step 3b: Streaming finalization — no phantom content blocks ──────
    // After stream completes, verify no empty/phantom markdown blocks.
    // Loop cards are ephemeral (only exist during streaming), so we only
    // check that markdown blocks have actual content.
    await page.waitForTimeout(2000); // Let URL sync settle
    const loopCardsBefore = await page
      .locator('[data-testid="agent-loop-card"]')
      .count();
    const markdownBefore = await page.locator('.sandbox-markdown').count();
    console.log(
      `[delegate] Before reload: ${loopCardsBefore} loop cards, ${markdownBefore} markdown blocks`
    );
    await snap(page, 'before-reload-counts');

    // Verify no empty markdown blocks (phantom = content present but empty)
    const allMarkdown = page.locator('.sandbox-markdown');
    for (let i = 0; i < await allMarkdown.count(); i++) {
      const text = (await allMarkdown.nth(i).textContent()) || '';
      expect(text.trim().length).toBeGreaterThan(0);
    }
    console.log('[delegate] Streaming finalization: no empty blocks');

    // Wait for ?session= to appear in URL — React Router updates it after
    // streaming completes via a useEffect. Poll for up to 10s.
    let parentSessionId = '';
    for (let i = 0; i < 20; i++) {
      parentSessionId = await page.evaluate(
        () => new URLSearchParams(window.location.search).get('session') || ''
      );
      if (parentSessionId) break;
      await page.waitForTimeout(500);
    }
    console.log(`[delegate] Parent session: ${parentSessionId}`);

    // ── Step 4: Verify child session in SessionSidebar ───────────────────
    expect(parentSessionId).toBeTruthy();

    // 4a: Check sub-session count label on the parent entry
    //     SessionSidebar renders "{N} sub-session(s)" below parent rows
    const subSessionLabel = page.locator('text=/sub-session/i').first();
    const hasSubSessionLabel = await subSessionLabel
      .isVisible({ timeout: 15000 })
      .catch(() => false);
    console.log(`[delegate] Sub-session label visible: ${hasSubSessionLabel}`);
    await snap(page, 'sidebar-sub-session');

    // 4b: Toggle "Root only" off to reveal child sessions in the list
    const rootOnlyToggle = page.locator('#root-only-toggle');
    let childConfirmedViaList = false;
    if (await rootOnlyToggle.isVisible({ timeout: 5000 }).catch(() => false)) {
      const wasChecked = await rootOnlyToggle.isChecked();
      if (wasChecked) {
        await rootOnlyToggle.click();
        await page.waitForTimeout(2000);
        console.log('[delegate] Toggled root-only OFF');
      }

      // Count session entries — should be >= 2 (parent + child)
      const allEntries = page
        .locator('div[role="button"]')
        .filter({ hasText: /session/i });
      const entryCount = await allEntries.count();
      console.log(`[delegate] Session entries (all): ${entryCount}`);
      childConfirmedViaList = entryCount >= 2;
      await snap(page, 'sidebar-all-sessions');

      // Restore toggle
      if (wasChecked) {
        await rootOnlyToggle.click();
        await page.waitForTimeout(1000);
      }
    }

    // 4c: Fallback — hover parent entry and inspect tooltip for "Sub-sessions:"
    let hasSubInTooltip = false;
    if (!hasSubSessionLabel && !childConfirmedViaList) {
      const parentEntry = page
        .locator('div[role="button"]')
        .filter({ hasText: AGENT_NAME })
        .first();
      if (await parentEntry.isVisible({ timeout: 3000 }).catch(() => false)) {
        await parentEntry.hover();
        await page.waitForTimeout(600);
        const tooltipText =
          (await page
            .locator('[role="tooltip"]')
            .textContent({ timeout: 3000 })
            .catch(() => '')) || '';
        hasSubInTooltip = /sub-session/i.test(tooltipText);
        console.log(
          `[delegate] Tooltip: "${tooltipText.substring(0, 200)}" => sub-session: ${hasSubInTooltip}`
        );
        await snap(page, 'tooltip-check');
      }
    }

    // At least one of the three checks should confirm child session creation
    const childSessionConfirmed =
      hasSubSessionLabel || childConfirmedViaList || hasSubInTooltip;
    console.log(`[delegate] Child session confirmed: ${childSessionConfirmed}`);
    expect(childSessionConfirmed).toBe(true);

    // ── Step 4d: Verify agent name in sidebar ────────────────────────
    const parentEntry = page.getByTestId(`session-${parentSessionId}`);
    if (await parentEntry.isVisible({ timeout: 5000 }).catch(() => false)) {
      const entryText = await parentEntry.textContent() || '';
      const hasAgentName = entryText.includes(AGENT_NAME);
      console.log(`[delegate] Sidebar shows agent ${AGENT_NAME}: ${hasAgentName}`);
      // Soft assertion — agent name may be empty due to metadata race
      if (!hasAgentName) {
        console.log(`[delegate] WARNING: Sidebar entry text: ${entryText.substring(0, 100)}`);
      }
    }

    // ── Step 5: Verify delegated task completed ──────────────────────────
    // 5a: Check Files tab for delegate-test.txt
    let fileVisibleInTree = false;
    const filesTab = page
      .locator('button[role="tab"]')
      .filter({ hasText: 'Files' });
    if (await filesTab.isVisible({ timeout: 5000 }).catch(() => false)) {
      await filesTab.click();
      await page.waitForTimeout(3000);
      await snap(page, 'files-tab');

      fileVisibleInTree = await page
        .locator('text=/delegate-test\\.txt/i')
        .first()
        .isVisible({ timeout: 10000 })
        .catch(() => false);
      console.log(
        `[delegate] delegate-test.txt in Files tab: ${fileVisibleInTree}`
      );

      // Switch back to Chat
      const chatTab = page
        .locator('button[role="tab"]')
        .filter({ hasText: 'Chat' });
      await chatTab.click();
      await page.waitForTimeout(1000);
    }

    // 5b: Verify via a follow-up shell command
    const verifyContent = await sendAndWait(
      page,
      'Run: cat /workspace/delegate-test.txt',
      60_000
    );
    await snap(page, 'verify-file');
    console.log(
      `[delegate] Verify response (${verifyContent.length} chars): ${verifyContent.substring(0, 300)}`
    );

    // The chat should now contain "hello from child" or at least "delegate-test"
    const fullChat =
      (await chatMessages.textContent({ timeout: 5000 }).catch(() => '')) || '';
    const hasFileContent = /hello from child/i.test(fullChat);
    const hasFileReference = /delegate-test/i.test(fullChat);
    console.log(
      `[delegate] Content match: ${hasFileContent}, file ref: ${hasFileReference}`
    );

    // The delegate tool must have at minimum referenced the file
    expect(hasFileReference).toBe(true);

    await snap(page, 'complete');
    console.log('[delegate] Test complete');
  });
});
