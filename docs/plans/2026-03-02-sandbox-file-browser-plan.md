# Sandbox File Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a file browser UI for exploring sandbox agent workspaces — directory tree, file preview with markdown/mermaid rendering, and code display.

**Architecture:** Backend uses K8s pod exec (`kubernetes.stream`) to list/read files inside sandbox agent pods. Frontend renders a split-pane (tree + preview) with PatternFly components, ReactMarkdown + remark-gfm for `.md` files, mermaid for diagrams, and PatternFly CodeBlock for code.

**Tech Stack:** FastAPI, kubernetes Python client (stream), React 18, PatternFly v5, ReactMarkdown (already installed), remark-gfm (already installed), mermaid (new dep), @tanstack/react-query.

---

### Task 1: Backend — sandbox_files.py router

**Files:**
- Create: `kagenti/backend/app/routers/sandbox_files.py`
- Modify: `kagenti/backend/app/main.py:34` (add import + router registration)

**Step 1: Create the router with Pydantic models and two endpoints**

```python
# kagenti/backend/app/routers/sandbox_files.py

import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client import ApiException
from kubernetes.stream import stream
from pydantic import BaseModel

from app.core.auth import ROLE_VIEWER, require_roles
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox-files"])

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB


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


class FileContent(BaseModel):
    path: str
    content: str
    size: int
    modified: str
    type: str
    encoding: str = "utf-8"


def _sanitize_path(path: str) -> str:
    """Ensure path is safe — must be under /workspace, no '..' traversal."""
    # Normalize and reject traversal
    if ".." in path:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not path.startswith("/workspace"):
        raise HTTPException(status_code=400, detail="Path must start with /workspace")
    return path


def _find_pod(kube: KubernetesService, namespace: str, agent_name: str) -> str:
    """Find a running pod for the given agent by label selector."""
    try:
        pods = kube.core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={agent_name}",
            timeout_seconds=10,
        )
    except ApiException as e:
        logger.error(f"Failed to list pods for {agent_name} in {namespace}: {e}")
        raise HTTPException(status_code=502, detail=f"K8s API error: {e.reason}")

    running = [
        p for p in pods.items
        if p.status and p.status.phase == "Running"
    ]
    if not running:
        raise HTTPException(
            status_code=404,
            detail=f"No running pod found for agent '{agent_name}' in namespace '{namespace}'",
        )
    return running[0].metadata.name


def _exec_in_pod(
    kube: KubernetesService, namespace: str, pod_name: str, command: list[str]
) -> str:
    """Execute a command in a pod and return stdout."""
    try:
        result = stream(
            kube.core_api.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return result
    except ApiException as e:
        logger.error(f"Exec failed in {pod_name}/{namespace}: {e}")
        raise HTTPException(status_code=502, detail=f"Pod exec failed: {e.reason}")


def _parse_ls_output(raw: str, base_path: str) -> list[FileEntry]:
    """Parse `ls -la --time-style=full-iso` output into FileEntry list."""
    entries = []
    for line in raw.strip().splitlines():
        # Skip header line ("total ...")
        if line.startswith("total "):
            continue
        # Format: permissions links owner group size date time timezone name
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        permissions = parts[0]
        size = int(parts[4]) if parts[4].isdigit() else 0
        # Date parts: parts[5] = date, parts[6] = time, parts[7] = tz
        modified = f"{parts[5]}T{parts[6]}{parts[7]}"
        name = parts[8]
        # Skip . and ..
        if name in (".", ".."):
            continue
        file_type: Literal["file", "directory"] = "directory" if permissions.startswith("d") else "file"
        path = f"{base_path.rstrip('/')}/{name}"
        entries.append(FileEntry(
            name=name,
            path=path,
            type=file_type,
            size=size,
            modified=modified,
            permissions=permissions,
        ))
    return entries


@router.get(
    "/{namespace}/files/{agent_name}",
    response_model=DirectoryListing | FileContent,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_files(
    namespace: str,
    agent_name: str,
    path: str = Query("/workspace", description="Absolute path inside the pod"),
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """List directory contents or read a file from a sandbox agent pod."""
    safe_path = _sanitize_path(path)
    pod_name = _find_pod(kube, namespace, agent_name)

    # First, determine if path is a file or directory
    file_test = _exec_in_pod(kube, namespace, pod_name, ["test", "-d", safe_path, "&&", "echo", "dir", "||", "echo", "file"])
    # Simpler approach: try ls -la on the path
    # If it's a directory, ls lists contents. If it's a file, ls shows the file entry.
    # We use stat to check type first.
    stat_output = _exec_in_pod(
        kube, namespace, pod_name,
        ["stat", "--format=%F|%s|%Y", safe_path],
    )
    stat_parts = stat_output.strip().split("|")

    if len(stat_parts) < 3:
        raise HTTPException(status_code=404, detail=f"Path not found: {safe_path}")

    file_type_str = stat_parts[0]  # "regular file" or "directory"
    file_size = int(stat_parts[1]) if stat_parts[1].isdigit() else 0

    if "directory" in file_type_str:
        # List directory
        ls_output = _exec_in_pod(
            kube, namespace, pod_name,
            ["ls", "-la", "--time-style=full-iso", safe_path],
        )
        entries = _parse_ls_output(ls_output, safe_path)
        return DirectoryListing(path=safe_path, entries=entries)
    else:
        # Read file
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({file_size} bytes). Max: {MAX_FILE_SIZE} bytes.",
            )
        content = _exec_in_pod(
            kube, namespace, pod_name,
            ["cat", safe_path],
        )
        # Get modification time
        mtime_output = _exec_in_pod(
            kube, namespace, pod_name,
            ["stat", "--format=%y", safe_path],
        )
        return FileContent(
            path=safe_path,
            content=content,
            size=file_size,
            modified=mtime_output.strip(),
            type="file",
        )
```

**Step 2: Register the router in main.py**

Add to `kagenti/backend/app/main.py` line 34:
```python
from app.routers import agents, tools, namespaces, config, auth, chat, sandbox_trigger, sandbox_files
```

Add after line 107:
```python
app.include_router(sandbox_files.router, prefix="/api/v1")
```

**Step 3: Verify backend starts**

Run: `cd kagenti/backend && uv run python -c "from app.routers.sandbox_files import router; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add kagenti/backend/app/routers/sandbox_files.py kagenti/backend/app/main.py
git commit -s -m "feat(sandbox): add file browser backend endpoint (Session H)"
```

---

### Task 2: Frontend — Install mermaid dependency

**Files:**
- Modify: `kagenti/ui-v2/package.json`

**Step 1: Install mermaid**

Run: `cd kagenti/ui-v2 && npm install mermaid`

Note: `react-markdown` and `remark-gfm` are already installed.

**Step 2: Verify installation**

Run: `cd kagenti/ui-v2 && node -e "require('mermaid'); console.log('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add kagenti/ui-v2/package.json kagenti/ui-v2/package-lock.json
git commit -s -m "feat(ui): add mermaid dependency for diagram rendering (Session H)"
```

---

### Task 3: Frontend — Types and API service

**Files:**
- Modify: `kagenti/ui-v2/src/types/index.ts` (add FileEntry, DirectoryListing, FileContent types)
- Modify: `kagenti/ui-v2/src/services/api.ts` (add sandboxFileService)

**Step 1: Add types to types/index.ts**

Append to end of file:
```typescript
// File browser types (Session H)
export interface FileEntry {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size: number;
  modified: string;
  permissions: string;
}

export interface DirectoryListing {
  path: string;
  entries: FileEntry[];
}

export interface FileContent {
  path: string;
  content: string;
  size: number;
  modified: string;
  type: string;
  encoding: string;
}
```

**Step 2: Add sandboxFileService to api.ts**

Append before the `chatService` export:
```typescript
/**
 * Sandbox file browser service (Session H)
 */
export const sandboxFileService = {
  async listDirectory(
    namespace: string,
    agentName: string,
    path: string = '/workspace'
  ): Promise<DirectoryListing> {
    const params = new URLSearchParams({ path });
    return apiFetch<DirectoryListing>(
      `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}?${params}`
    );
  },

  async getFileContent(
    namespace: string,
    agentName: string,
    path: string
  ): Promise<FileContent> {
    const params = new URLSearchParams({ path });
    return apiFetch<FileContent>(
      `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}?${params}`
    );
  },
};
```

Add `DirectoryListing, FileContent` to the import from `@/types` at top of api.ts.

**Step 3: Verify typecheck**

Run: `cd kagenti/ui-v2 && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add kagenti/ui-v2/src/types/index.ts kagenti/ui-v2/src/services/api.ts
git commit -s -m "feat(ui): add file browser types and API service (Session H)"
```

---

### Task 4: Frontend — FilePreview.tsx component

**Files:**
- Create: `kagenti/ui-v2/src/components/FilePreview.tsx`

This component renders:
- `.md` files with ReactMarkdown + remark-gfm + mermaid code blocks
- Code files with PatternFly CodeBlock
- File metadata bar (size, modified, permissions)

**Step 1: Create FilePreview.tsx**

```tsx
// kagenti/ui-v2/src/components/FilePreview.tsx
import React, { useEffect, useRef } from 'react';
import {
  CodeBlock,
  CodeBlockCode,
  Spinner,
  Title,
  Label,
  Split,
  SplitItem,
} from '@patternfly/react-core';
import { FileIcon } from '@patternfly/react-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';

import type { FileContent } from '@/types';

// Initialize mermaid once
mermaid.initialize({ startOnLoad: false, theme: 'default' });

interface FilePreviewProps {
  file: FileContent | null;
  isLoading: boolean;
}

/** Render a mermaid diagram inside a fenced code block. */
const MermaidBlock: React.FC<{ chart: string }> = ({ chart }) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`;
    mermaid.render(id, chart).then(({ svg }) => {
      if (ref.current) ref.current.innerHTML = svg;
    }).catch(() => {
      if (ref.current) ref.current.textContent = chart;
    });
  }, [chart]);

  return <div ref={ref} />;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getLanguage(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, string> = {
    py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript',
    jsx: 'javascript', json: 'json', yaml: 'yaml', yml: 'yaml',
    sh: 'bash', bash: 'bash', css: 'css', html: 'html', sql: 'sql',
    go: 'go', rs: 'rust', java: 'java', rb: 'ruby', toml: 'toml',
  };
  return map[ext] || 'text';
}

function isMarkdown(path: string): boolean {
  return /\.(md|mdx|markdown)$/i.test(path);
}

export const FilePreview: React.FC<FilePreviewProps> = ({ file, isLoading }) => {
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spinner aria-label="Loading file..." />
      </div>
    );
  }

  if (!file) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--pf-v5-global--Color--200)' }}>
        Select a file to preview
      </div>
    );
  }

  const fileName = file.path.split('/').pop() || file.path;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Metadata bar */}
      <div style={{
        padding: '8px 16px',
        borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}>
        <FileIcon />
        <Title headingLevel="h3" size="md" style={{ margin: 0 }}>{fileName}</Title>
        <Split hasGutter style={{ marginLeft: 'auto' }}>
          <SplitItem>
            <Label isCompact>{formatSize(file.size)}</Label>
          </SplitItem>
          <SplitItem>
            <Label isCompact color="blue">{file.modified}</Label>
          </SplitItem>
        </Split>
      </div>

      {/* Content area */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {isMarkdown(file.path) ? (
          <div className="pf-v5-c-content">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');
                  const lang = match ? match[1] : '';
                  const codeString = String(children).replace(/\n$/, '');

                  if (lang === 'mermaid') {
                    return <MermaidBlock chart={codeString} />;
                  }

                  // Block code
                  if (className) {
                    return (
                      <CodeBlock>
                        <CodeBlockCode>{codeString}</CodeBlockCode>
                      </CodeBlock>
                    );
                  }
                  // Inline code
                  return <code {...props}>{children}</code>;
                },
              }}
            >
              {file.content}
            </ReactMarkdown>
          </div>
        ) : (
          <CodeBlock>
            <CodeBlockCode>{file.content}</CodeBlockCode>
          </CodeBlock>
        )}
      </div>
    </div>
  );
};
```

**Step 2: Verify typecheck**

Run: `cd kagenti/ui-v2 && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add kagenti/ui-v2/src/components/FilePreview.tsx
git commit -s -m "feat(ui): FilePreview component with markdown + mermaid rendering (Session H)"
```

---

### Task 5: Frontend — FileBrowser.tsx component

**Files:**
- Create: `kagenti/ui-v2/src/components/FileBrowser.tsx`

Split-pane layout: left panel has directory tree (PatternFly TreeView), right panel has FilePreview. Breadcrumb navigation at top.

**Step 1: Create FileBrowser.tsx**

```tsx
// kagenti/ui-v2/src/components/FileBrowser.tsx
import React, { useState, useCallback } from 'react';
import {
  Breadcrumb,
  BreadcrumbItem,
  Card,
  CardBody,
  PageSection,
  Spinner,
  TreeView,
  TreeViewDataItem,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Title,
  Alert,
} from '@patternfly/react-core';
import {
  FolderIcon,
  FolderOpenIcon,
  FileIcon,
  FileCodeIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';

import { sandboxFileService } from '@/services/api';
import { FilePreview } from './FilePreview';
import type { FileEntry, FileContent, DirectoryListing } from '@/types';

function getFileIcon(entry: FileEntry) {
  if (entry.type === 'directory') return FolderIcon;
  if (/\.(py|ts|tsx|js|jsx|go|rs|java|rb|sh)$/i.test(entry.name)) return FileCodeIcon;
  return FileIcon;
}

interface TreeNode extends TreeViewDataItem {
  entry?: FileEntry;
}

export const FileBrowser: React.FC = () => {
  const { namespace, agentName } = useParams<{ namespace: string; agentName: string }>();
  const [currentPath, setCurrentPath] = useState('/workspace');
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['/workspace']));

  // Fetch directory listing for current path
  const {
    data: dirListing,
    isLoading: isDirLoading,
    error: dirError,
  } = useQuery({
    queryKey: ['sandbox-files', namespace, agentName, currentPath],
    queryFn: () => sandboxFileService.listDirectory(namespace!, agentName!, currentPath),
    enabled: !!namespace && !!agentName,
    staleTime: 15000,
  });

  // Fetch file content when a file is selected
  const {
    data: fileContent,
    isLoading: isFileLoading,
  } = useQuery({
    queryKey: ['sandbox-file-content', namespace, agentName, selectedFilePath],
    queryFn: () => sandboxFileService.getFileContent(namespace!, agentName!, selectedFilePath!),
    enabled: !!namespace && !!agentName && !!selectedFilePath,
    staleTime: 30000,
  });

  const handleEntryClick = useCallback((entry: FileEntry) => {
    if (entry.type === 'directory') {
      setCurrentPath(entry.path);
      setExpandedPaths(prev => {
        const next = new Set(prev);
        next.add(entry.path);
        return next;
      });
      setSelectedFilePath(null);
    } else {
      setSelectedFilePath(entry.path);
    }
  }, []);

  // Build breadcrumb segments from current path
  const breadcrumbSegments = currentPath.split('/').filter(Boolean);

  const handleBreadcrumbClick = (index: number) => {
    const path = '/' + breadcrumbSegments.slice(0, index + 1).join('/');
    setCurrentPath(path);
    setSelectedFilePath(null);
  };

  // Convert entries to TreeView data
  const treeData: TreeNode[] = (dirListing?.entries || [])
    .sort((a, b) => {
      // Directories first, then alphabetical
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1;
      return a.name.localeCompare(b.name);
    })
    .map((entry) => ({
      id: entry.path,
      name: entry.name,
      icon: React.createElement(getFileIcon(entry)),
      entry,
      ...(entry.type === 'directory' ? { children: [] } : {}),
    }));

  if (!namespace || !agentName) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader titleText="No agent selected" headingLevel="h2" icon={<EmptyStateIcon icon={ExclamationTriangleIcon} />} />
          <EmptyStateBody>Navigate to /sandbox/files/:namespace/:agentName</EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  return (
    <PageSection variant="light" padding={{ default: 'noPadding' }}>
      {/* Breadcrumb */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)' }}>
        <Breadcrumb>
          {breadcrumbSegments.map((seg, i) => (
            <BreadcrumbItem
              key={i}
              isActive={i === breadcrumbSegments.length - 1}
              onClick={() => handleBreadcrumbClick(i)}
              component={i === breadcrumbSegments.length - 1 ? 'span' : 'button'}
            >
              {seg}
            </BreadcrumbItem>
          ))}
        </Breadcrumb>
        <Title headingLevel="h2" size="lg" style={{ marginTop: 4 }}>
          {agentName} — File Browser
        </Title>
      </div>

      {dirError && (
        <Alert variant="danger" title={String(dirError)} isInline style={{ margin: 16 }} />
      )}

      {/* Split pane: tree (left) + preview (right) */}
      <div style={{ display: 'flex', height: 'calc(100vh - 160px)' }}>
        {/* Left panel — directory listing */}
        <div style={{
          width: 320,
          borderRight: '1px solid var(--pf-v5-global--BorderColor--100)',
          overflow: 'auto',
          padding: 8,
        }}>
          {isDirLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
              <Spinner aria-label="Loading directory..." />
            </div>
          ) : (
            <TreeView
              data={treeData}
              activeItems={selectedFilePath ? treeData.filter(n => n.id === selectedFilePath) : []}
              onSelect={(_event, item) => {
                const node = item as TreeNode;
                if (node.entry) handleEntryClick(node.entry);
              }}
              hasGuides
            />
          )}
        </div>

        {/* Right panel — file preview */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <FilePreview
            file={fileContent as FileContent | null ?? null}
            isLoading={isFileLoading}
          />
        </div>
      </div>
    </PageSection>
  );
};
```

**Step 2: Verify typecheck**

Run: `cd kagenti/ui-v2 && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add kagenti/ui-v2/src/components/FileBrowser.tsx
git commit -s -m "feat(ui): FileBrowser split-pane component with tree view (Session H)"
```

---

### Task 6: Frontend — Route and navigation

**Files:**
- Modify: `kagenti/ui-v2/src/App.tsx` (add route)
- Modify: `kagenti/ui-v2/src/components/AppLayout.tsx` (add nav item)

**Step 1: Add route in App.tsx**

Add import at top:
```typescript
import { FileBrowser } from './components/FileBrowser';
```

Add route before the `<Route path="*"` catch-all:
```tsx
<Route
  path="/sandbox/files/:namespace/:agentName"
  element={
    <ProtectedRoute>
      <FileBrowser />
    </ProtectedRoute>
  }
/>
```

**Step 2: Add nav item in AppLayout.tsx**

Add inside the "Agentic Workloads" `NavGroup`, after "Tools":
```tsx
<NavItem
  itemId="file-browser"
  isActive={isNavItemActive('/sandbox/files')}
  onClick={() => handleNavSelect('/sandbox/files')}
>
  Files
</NavItem>
```

Note: Clicking "Files" nav without namespace/agent shows the EmptyState. Users will typically navigate here from agent detail or session chat links.

**Step 3: Verify app builds**

Run: `cd kagenti/ui-v2 && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add kagenti/ui-v2/src/App.tsx kagenti/ui-v2/src/components/AppLayout.tsx
git commit -s -m "feat(ui): add file browser route and nav item (Session H)"
```

---

### Task 7: E2E test — sandbox-file-browser.spec.ts

**Files:**
- Create: `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts`

Tests use API mocking (page.route) — no live cluster required.

**Step 1: Create the test file**

```typescript
// kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts
import { test, expect, type Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

const MOCK_DIR_LISTING = {
  path: '/workspace',
  entries: [
    { name: 'src', path: '/workspace/src', type: 'directory', size: 4096, modified: '2026-03-02T10:00:00+00:00', permissions: 'drwxr-xr-x' },
    { name: 'README.md', path: '/workspace/README.md', type: 'file', size: 256, modified: '2026-03-02T09:30:00+00:00', permissions: '-rw-r--r--' },
    { name: 'main.py', path: '/workspace/main.py', type: 'file', size: 1024, modified: '2026-03-02T09:00:00+00:00', permissions: '-rw-r--r--' },
  ],
};

const MOCK_MD_CONTENT = {
  path: '/workspace/README.md',
  content: '# Hello World\n\nThis is a **test** markdown file.\n\n```mermaid\ngraph TD\n  A-->B\n```\n',
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
  const submitButton = page.locator('#kc-login, button[type="submit"], input[type="submit"]').first();
  if (await usernameField.isVisible({ timeout: 3000 }).catch(() => false)) {
    await usernameField.fill(KEYCLOAK_USER);
    await passwordField.fill(KEYCLOAK_PASSWORD);
    await submitButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }
}

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

test.describe('Sandbox File Browser (Session H)', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockRoutes(page);
  });

  test('renders directory listing with entries', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await loginIfNeeded(page);
    await page.waitForSelector('[class*="pf-v5-c-tree-view"]', { timeout: 15000 });

    // Check all 3 entries are visible
    await expect(page.getByText('src')).toBeVisible();
    await expect(page.getByText('README.md')).toBeVisible();
    await expect(page.getByText('main.py')).toBeVisible();
  });

  test('shows empty state when no agent selected', async ({ page }) => {
    await page.goto('/sandbox/files');
    await loginIfNeeded(page);
    // Should show 404 or empty state
    await expect(page.getByText(/No agent selected|not found/i)).toBeVisible({ timeout: 10000 });
  });

  test('click .md file shows markdown preview with mermaid', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await loginIfNeeded(page);
    await page.waitForSelector('[class*="pf-v5-c-tree-view"]', { timeout: 15000 });

    await page.getByText('README.md').click();
    // Should render markdown heading
    await expect(page.locator('h1:has-text("Hello World")')).toBeVisible({ timeout: 10000 });
    // Should render bold text
    await expect(page.locator('strong:has-text("test")')).toBeVisible();
    // Mermaid diagram should render (as SVG)
    await expect(page.locator('svg')).toBeVisible({ timeout: 10000 });
  });

  test('click code file shows code block', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await loginIfNeeded(page);
    await page.waitForSelector('[class*="pf-v5-c-tree-view"]', { timeout: 15000 });

    await page.getByText('main.py').click();
    // Should show code in CodeBlock
    await expect(page.locator('[class*="pf-v5-c-code-block"]')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('def hello():')).toBeVisible();
  });

  test('breadcrumb navigation shows path segments', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await loginIfNeeded(page);

    // Should show breadcrumb with "workspace"
    await expect(page.locator('[class*="pf-v5-c-breadcrumb"]')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('workspace')).toBeVisible();
  });

  test('file metadata displays size and date', async ({ page }) => {
    await page.goto('/sandbox/files/team1/sandbox-basic');
    await loginIfNeeded(page);
    await page.waitForSelector('[class*="pf-v5-c-tree-view"]', { timeout: 15000 });

    await page.getByText('README.md').click();
    // Should show file size label
    await expect(page.getByText('256 B')).toBeVisible({ timeout: 10000 });
  });
});
```

**Step 2: Verify test can be listed**

Run: `cd kagenti/ui-v2 && npx playwright test --list sandbox-file-browser.spec.ts`
Expected: Lists 6 tests

**Step 3: Commit**

```bash
git add kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts
git commit -s -m "test(ui): add file browser Playwright E2E tests (Session H)"
```

---

### Task 8: Update passover doc — register Session H

**Files:**
- Modify: `docs/plans/2026-03-01-multi-session-passover.md`

**Step 1: Pull latest**

Run: `git pull --rebase origin fix/hypershift-ci-deploy`

**Step 2: Add Session H section and cross-session TODO**

Add Session H definition after Session E, and add a cross-session TODO requesting Session A to add file path links in SandboxPage.tsx chat messages.

**Step 3: Commit**

```bash
git add docs/plans/2026-03-01-multi-session-passover.md
git commit -s -m "docs: register Session H (File Browser) in passover doc"
```
