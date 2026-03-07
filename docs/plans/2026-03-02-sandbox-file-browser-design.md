# Sandbox File Browser Design

> **Date:** 2026-03-02
> **Session:** H (Sandbox File Browser)
> **Status:** Approved

## Overview

A file browser UI for exploring sandbox agent workspaces. Users can browse the
filesystem hierarchy inside a running sandbox pod and preview file contents —
markdown files render with full formatting, code files get syntax highlighting.

## Backend API

**Router:** `kagenti/backend/app/routers/sandbox_files.py`

### Endpoints

```
GET /api/v1/sandbox/{namespace}/files/{agent_name}?path=/workspace
```

- **Directory:** execs `ls -la --time-style=full-iso` into the sandbox pod via K8s
  `stream()`, parses output into structured JSON entries.
- **File:** execs `cat` into the pod, returns content + metadata.
- **Pod discovery:** label selector `app={agent_name}` in the given namespace.
- **Auth:** `require_roles(ROLE_VIEWER)` — read-only.
- **Safety:** Path must start with `/workspace`, no `..` traversal, 1MB file size cap.

### Response Models

```python
# Directory listing
class FileEntry(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int
    modified: str
    permissions: str

class DirectoryListing(BaseModel):
    path: str
    entries: list[FileEntry]

# File content
class FileContent(BaseModel):
    path: str
    content: str
    size: int
    modified: str
    type: Literal["file", "directory"]
    encoding: str = "utf-8"
```

## Frontend

### Components

| File | Purpose |
|------|---------|
| `FileBrowser.tsx` | Split-pane: tree (left 300px) + preview (right flex-1) + breadcrumb bar |
| `FilePreview.tsx` | Content viewer: markdown rendering, syntax highlighting, metadata |

### Navigation

- Nav item "Files" under "Agentic Workloads" group in AppLayout.tsx
- Route: `/sandbox/files/:namespace/:agentName`
- Breadcrumb: `/ > workspace > src > file.py` (clickable segments)

### Libraries

- `react-markdown` + `remark-gfm` for .md preview
- `react-syntax-highlighter` for code files
- PatternFly `TreeView` for directory tree

### API Service

Add `sandboxFileService` to `api.ts`:
- `listDirectory(namespace, agentName, path)` → `DirectoryListing`
- `getFileContent(namespace, agentName, path)` → `FileContent`

## Integration

### Cross-Session TODO

Session A owns `SandboxPage.tsx`. To make file paths in chat messages clickable
(linking to the file browser), Session A needs to add a link renderer. This is
a post-merge integration — added as Cross-Session TODO in passover doc.

## File Ownership (Session H — EXCLUSIVE)

- `kagenti/backend/app/routers/sandbox_files.py` (new)
- `kagenti/ui-v2/src/components/FileBrowser.tsx` (new)
- `kagenti/ui-v2/src/components/FilePreview.tsx` (new)
- `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts` (new)

## E2E Tests

`sandbox-file-browser.spec.ts`:
1. Navigate to file browser page
2. Directory listing renders with entries
3. Click folder → children load
4. Click .md file → markdown preview renders
5. Click code file → syntax highlighted preview
6. Breadcrumb navigation works
7. File metadata (size, modified) displayed
