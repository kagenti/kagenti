---
name: test:ui-sandbox
description: Playwright selector patterns for sandbox agent chat — proven selectors for sessions, agents, messages, tool calls
---

# Sandbox UI Test Patterns

Proven Playwright selectors and patterns for testing the Kagenti sandbox agent chat UI.
Based on 20+ iterations of debugging on live HyperShift clusters.

## Agent Selection

```typescript
// Select an agent in the Sandboxes sidebar (proven pattern from sandbox-variants)
const agentEntry = page.locator('div[role="button"]').filter({
  hasText: agentName,
}).filter({
  hasText: /session/i,  // Agents show "N sessions" text
});
await expect(agentEntry.first()).toBeVisible({ timeout: 30000 });
await agentEntry.first().click();
```

## Chat Input

```typescript
// Message input (SandboxPage)
const input = page.locator('textarea[aria-label="Message input"]');
await input.fill('my message');
await input.press('Enter');  // Enter sends (not click Send button)

// Or via Send button
await page.getByRole('button', { name: /Send/i }).click();
```

## Agent Response Detection

The agent may respond with **text** (`.sandbox-markdown`) or **tool calls** (ToolCallStep divs).
Always check for both:

```typescript
// Wait for ANY agent output (text or tool calls)
const agentOutput = page.locator('.sandbox-markdown')
  .or(page.locator('text=/Tool Call:|Result:/i'));
await expect(agentOutput.first()).toBeVisible({ timeout: 180000 });

// Count each type
const mdCount = await page.locator('.sandbox-markdown').count();
const toolCount = await page.locator('text=/Tool Call:|Result:/i').count();
```

### .sandbox-markdown

Renders for assistant messages with text content (not tool calls):
```html
<div class="sandbox-markdown">
  <ReactMarkdown>response text here</ReactMarkdown>
</div>
```

### ToolCallStep

Renders for tool_call and tool_result events. Uses `<div>` with click handler, NOT `<details>`:
```html
<div style="border-left: 3px solid ...">
  <div style="font-weight: 600">▶ Tool Call: web_fetch</div>
</div>
```

Selector: `page.locator('text=/Tool Call:|Result:/i')`

## Session URL & Navigation

### Capture session URL from test 3 for reuse in tests 4-6:
```typescript
let sessionUrl: string | null = null;

// After sending message and getting response:
sessionUrl = page.url();
// URL format: /sandbox?session=<context_id>
```

### Navigate to session (avoiding Keycloak re-auth redirect):

**WRONG** — triggers full page load through Keycloak, redirects to `/`:
```typescript
await page.goto(sessionUrl); // Keycloak redirects to /
```

**RIGHT** — SPA routing via pushState:
```typescript
await page.goto('/');
await loginIfNeeded(page);
const sid = sessionUrl.match(/session=([a-f0-9]+)/)?.[1];
await page.evaluate((s) => {
  window.history.pushState({}, '', `/sandbox?session=${s}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}, sid);
// pushState triggers sync React re-render — no DOM indicator to await
    await page.waitForTimeout(5000);
```

## History Loading (toMessage conversion)

When a session reloads from history, the backend's paginated history API converts
agent messages into `kind: "data"` parts. The frontend `toMessage()` function
must distinguish tool calls from text:

- `kind: "data"` + `type: "tool_call"` → renders as ToolCallStep
- `kind: "data"` + `type: "tool_result"` → renders as ToolCallStep
- `kind: "data"` + `type: "llm_response"` → should render as .sandbox-markdown
- `kind: "text"` → always renders as .sandbox-markdown

## Known Issues

1. **rca-agent shows "0 sessions"** — sessions not tagged with agent name in metadata
2. **TOFU PermissionError** — agent Dockerfile needs `chmod g+w /app` for OCP arbitrary UID
3. **SSE rendering flaky** — `.sandbox-markdown` sometimes doesn't appear during streaming
   (tool calls render, but final text may not). Workaround: poll with retry.

## Test Structure for Serial Agent Tests

```typescript
test.describe('Agent Workflow', () => {
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(300000);
  let sessionUrl: string | null = null;

  test.beforeAll(() => { /* cleanup agent */ });

  test('1 — deploy', async ({ page }) => { /* wizard + patch */ });
  test('2 — verify card', async ({ page }) => { /* kubectl exec httpx */ });
  test('3 — send message', async ({ page }) => {
    // ... send and wait for response ...
    sessionUrl = page.url();
  });
  test('4 — reload session', async ({ page }) => {
    // Login first, then SPA-navigate to sessionUrl
  });
});
```
