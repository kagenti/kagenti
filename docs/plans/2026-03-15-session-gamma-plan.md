# Session Gamma (γ) — Graph Feedback + File Browser + Draft Chat

> **Date:** 2026-03-15
> **Cluster:** kagenti-team-sandbox42
> **Branch:** `feat/sandbox-agent`

## Feature 1: Graph View Feedback Chat

### Problem
When browsing agent run results in the graph view (right column), there's no way to:
- Copy content from a step's output
- Provide feedback or corrections
- Start a new message referencing specific results

### Design

Add a **persistent chat input** to the graph view's right column:

```
┌─────────────────────────────────────┐
│ Graph DAG (left)  │ Step Detail     │
│                   │ (right column)  │
│  [planner]───┐    │                 │
│              │    │ Step 3: shell   │
│  [executor]──┤    │ Output: ...     │
│              │    │ [Copy] [Quote]  │
│  [reflector]─┘    │                 │
│                   │─────────────────│
│                   │ 💬 Draft Chat   │
│                   │ [textarea]      │
│                   │ [Send] [Clear]  │
│                   │                 │
│                   │ Quoted:         │
│                   │ > step 3 output │
└─────────────────────────────────────┘
```

- **Quote button** on each step output → appends quoted content to draft
- **Copy button** → copies to clipboard (existing)
- **Draft textarea** persists across page navigation (session-level state)
- **Send** → sends message to the agent with quoted context
- Draft content visible in all session views (graph, chat, file browser)

### Implementation

1. **Draft state** — `useRef` or `localStorage` keyed by session ID:
   ```typescript
   const [draftMessage, setDraftMessage] = useState<string>('');
   // Persist across tab switches via sessionStorage
   useEffect(() => {
     sessionStorage.setItem(`draft-${contextId}`, draftMessage);
   }, [draftMessage, contextId]);
   ```

2. **Quote action** on step detail:
   ```typescript
   const handleQuote = (content: string, stepLabel: string) => {
     setDraftMessage(prev => prev + `\n> ${stepLabel}: ${content.substring(0, 200)}\n`);
   };
   ```

3. **ChatInput component** — reusable, shown in graph view + file browser:
   ```typescript
   <DraftChat
     value={draftMessage}
     onChange={setDraftMessage}
     onSend={handleSendMessage}
     placeholder="Reply with feedback..."
   />
   ```

### Fix: UTF-8 Button Icons

Some buttons in the right expandable column show garbled UTF characters.
Likely caused by icon components not rendering properly. Check:
- PatternFly icon imports (may need explicit font loading)
- Or replace Unicode symbols with PatternFly `<Icon>` components

## Feature 2: File Browser Enhancements

### 2a: Fullscreen Button for Every File

Add a fullscreen toggle to file preview cards:

```
┌─────────────────────────────────────┐
│ 📄 repos/kagenti/README.md    [⛶]  │  ← fullscreen button
│─────────────────────────────────────│
│ # Kagenti                           │
│ Cloud-native middleware...          │
└─────────────────────────────────────┘
```

When fullscreen:
- File content takes full viewport (like PromptInspector portal)
- Draft chat visible at bottom (persistent across views)
- Close with ESC or X button

### 2b: Git Diff View

If file is under git, add a toggle: **Preview | Diff**

```
┌──────────────────────────────────────┐
│ 📄 src/graph.py  [Preview] [Diff] [⛶]│
│──────────────────────────────────────│
│ - old line                           │
│ + new line with per-node LLM         │
│   unchanged context                  │
└──────────────────────────────────────┘
```

**Backend endpoint needed:**
```
GET /api/v1/sandbox/{ns}/files/{agent}/diff?path=src/graph.py&context_id=xxx
```

Returns unified diff from `git diff` in the workspace.

### 2c: Directory Preview with Git Status

When browsing a directory, show:

```
┌──────────────────────────────────────┐
│ 📁 repos/kagenti/               [⛶] │
│──────────────────────────────────────│
│ Branch: feat/sandbox-agent           │
│ Status: 3 modified, 1 untracked     │
│                                      │
│  M  src/graph.py                     │
│  M  src/configuration.py             │
│  M  src/context_builders.py          │
│  ?  src/new_file.py                  │
│                                      │
│ ── Full Diff (lazy load) ──          │
│ [Show diff for all changed files]    │
└──────────────────────────────────────┘
```

**Backend endpoint needed:**
```
GET /api/v1/sandbox/{ns}/files/{agent}/git-status?path=repos/kagenti&context_id=xxx
```

Returns: `{ branch, status: [{path, status}], diff_available: true }`

```
GET /api/v1/sandbox/{ns}/files/{agent}/git-diff-all?path=repos/kagenti&context_id=xxx
```

Returns: full repo diff (lazy loaded, paginated)

### 2d: Draft Chat in Fullscreen File Browser

The fullscreen file browser should show the draft chat at the bottom:

```
┌──────────────────────────────────────────────────┐
│ 📁 File Browser (fullscreen)              [Close]│
│──────────────────────────────────────────────────│
│                                                  │
│  File content / directory listing                │
│  (scrollable)                                    │
│                                                  │
│──────────────────────────────────────────────────│
│ 💬 Draft: "Please fix the workspace_path..."     │
│ [Send] [Clear]                                   │
└──────────────────────────────────────────────────┘
```

Draft text persists across:
- Chat view ↔ Graph view ↔ File browser
- Tab switches within a session
- NOT across sessions (each session has its own draft)

## Feature 3: Draft Message Persistence

### Storage

```typescript
// Per-session draft stored in sessionStorage
const DRAFT_KEY = (contextId: string) => `kagenti-draft-${contextId}`;

// On mount: restore draft
useEffect(() => {
  const saved = sessionStorage.getItem(DRAFT_KEY(contextId));
  if (saved) setDraftMessage(saved);
}, [contextId]);

// On change: save draft
useEffect(() => {
  if (draftMessage) {
    sessionStorage.setItem(DRAFT_KEY(contextId), draftMessage);
  } else {
    sessionStorage.removeItem(DRAFT_KEY(contextId));
  }
}, [draftMessage, contextId]);

// On send: clear draft
const handleSend = () => {
  handleSendMessage();
  setDraftMessage('');
  sessionStorage.removeItem(DRAFT_KEY(contextId));
};
```

### Visibility

| View | Draft Visible? | Can Quote? |
|------|---------------|------------|
| Chat (main) | Yes (input area) | No (it IS the input) |
| Graph view (right column) | Yes (bottom panel) | Yes (from step outputs) |
| File browser (inline) | No (too small) | No |
| File browser (fullscreen) | Yes (bottom panel) | Yes (from file content) |

## Implementation Order

1. **UTF-8 fix** — quick, check icon rendering in graph right column
2. **Draft state** — `sessionStorage` persistence per session
3. **Quote button** on graph step outputs
4. **DraftChat component** — reusable textarea + send
5. **Fullscreen file preview** — portal like PromptInspector
6. **Git diff view** — backend endpoint + UI toggle
7. **Directory git status** — backend endpoint + UI

## Files to Change

```
UI:
  src/pages/SandboxPage.tsx          # draft state, sessionStorage
  src/components/GraphView.tsx       # quote buttons, DraftChat
  src/components/LoopDetail.tsx      # quote buttons on step outputs
  src/components/FilePreview.tsx     # fullscreen, git diff toggle
  src/components/DraftChat.tsx       # NEW — reusable chat input
  src/components/FileBrowser.tsx     # directory git status

Backend:
  app/routers/sandbox_files.py      # git-diff, git-status endpoints
```
