# Session-Scoped File Browser with Universal Preview Popup

**Date**: 2026-03-05
**Status**: Design approved
**Session**: L

## Problem

The file browser currently operates at the agent level (`/sandbox/files/:namespace/:agentName`) with no session scoping. Users can browse the entire pod filesystem, see other sessions' files, and there's no RBAC enforcement. File paths mentioned in chat are plain text with no way to preview or navigate to them.

## Design

### 1. URL & Routing

**New route**: `/sandbox/files/:namespace/:agentName/:contextId`

- Backend enforces paths stay within `/workspace/{contextId}/`
- Breadcrumb: `workspace` > `{contextId}` > `subdir` > ...
- Title: `{agentName} — Session {contextId}`
- Old route kept for backward compat (shows all workspaces)

### 2. FilePreviewModal — Universal Popup Component

A single reusable modal for previewing files anywhere in the UI:

- **Trigger**: clicking a file in the tree, clicking a file path card in chat
- **Header**: file icon + filename + size + date + [Fullscreen] [Open in Browser] [✕]
- **Body**: FilePreview component (markdown/code/binary guard) wrapped in ErrorBoundary
- **Fullscreen**: toggle button expands modal to fill viewport (PatternFly `Modal isFullScreen`)
- **On hover** (when card trigger): tooltip "Click for details"

Used in:
- `FileBrowser` — tree click → popup (replaces inline right-panel preview)
- `ChatMessage` — file path card → popup
- Any future file reference in the UI

### 3. FilePathCard — Chat File Links

Inline component rendered in chat messages when file paths are detected:

- **Detection**: file paths from `file_write` tool results, or `/workspace/...` patterns in text
- **Render**: small card with file icon + filename + optional size
- **On hover**: tooltip "Click for details"
- **On click**: opens `FilePreviewModal` with the file content

### 4. Agent RCA Reports (Prompt Change)

The planner system prompt in `reasoning.py` instructs the agent to create `.md` report files for complex tasks:

> For multi-step analysis, debugging, or investigation tasks, write a structured summary to a .md file in the workspace as the final step. Include sections: Problem, Investigation, Root Cause, Resolution.

### 5. Backend: Path Enforcement

`sandbox_files.py` changes:
- New route: `/{namespace}/files/{agent_name}/{context_id}`
- Prepends `/workspace/{context_id}/` to all paths
- Rejects paths that escape the context workspace via `..`
- Session-based RBAC: verify the requesting user owns the session (future)

### 6. Parent Folder Navigation

- Breadcrumb segments are all clickable — clicking any segment navigates up
- Clicking `workspace` goes to the workspace root (shows all context directories)
- No filesystem `..` traversal — navigation is breadcrumb-only

### 7. Tests

| Test | What |
|------|------|
| Session workspace landing | URL with contextId, breadcrumb shows it, files scoped |
| Parent folder navigation | Click breadcrumb to go up, tree updates |
| Path traversal rejection | API returns 400 for `../../other-session/` |
| File preview popup opens | Click file → modal visible with content |
| Popup fullscreen toggle | Click fullscreen → modal expands |
| Chat file link card | Agent response with file path → FilePathCard rendered |
| Chat file link popup | Click card → FilePreviewModal with content |
| Binary file in popup | Binary file → "preview not available" in modal |
| Preview crash in popup | Bad content → ErrorBoundary fallback in modal |
| Context ID visible | Title and breadcrumb show session context ID |

## Component Architecture

```
FilePreviewModal (new)
├── Header: filename + size + date + [Fullscreen] [Open in Browser] [✕]
├── Body: FilePreview (markdown/code/binary guard)
└── ErrorBoundary wrapping Body

FileBrowser (modified)
├── Breadcrumb: workspace > {contextId} > ...
├── Title: agentName — Session {contextId}
├── TreeView (full width — no split pane)
│   └── onClick → opens FilePreviewModal
└── FilePreviewModal

ChatMessage (modified)
├── Existing text/tool_call rendering
├── FilePathCard (new) — detected file paths
│   └── onClick → opens FilePreviewModal
└── FilePreviewModal
```

## Files to Change

| File | Change |
|------|--------|
| `FileBrowser.tsx` | Add contextId param, remove right panel, open popup on click |
| `FilePreview.tsx` | No change (already handles binary/error) |
| `FilePreviewModal.tsx` | **NEW** — Modal wrapper with fullscreen toggle |
| `FilePathCard.tsx` | **NEW** — Inline card for chat file paths |
| `ChatMessage.tsx` or equivalent | Detect file paths, render FilePathCard |
| `App.tsx` | Add route with `:contextId` param |
| `sandbox_files.py` | Add context_id route, enforce path scoping |
| `reasoning.py` | Add RCA report instruction to planner prompt |
| `sandbox-file-browser.spec.ts` | Add all tests from table above |
