# Session-Scoped File Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add session workspace scoping, universal file preview popup, and chat file path cards to the file browser.

**Architecture:** The file browser route gains a `:contextId` param that scopes browsing to `/workspace/{contextId}/`. A reusable `FilePreviewModal` (PatternFly Modal with fullscreen toggle) replaces inline preview everywhere. The existing `linkifyFilePaths` in SandboxPage is upgraded to render `FilePathCard` components that open the modal on click.

**Tech Stack:** React, PatternFly v5 (Modal, CodeBlock, TreeView), @tanstack/react-query, Playwright, FastAPI

---

### Task 1: FilePreviewModal component

**Files:**
- Create: `kagenti/ui-v2/src/components/FilePreviewModal.tsx`
- Test: `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts`

**Step 1: Write the failing test**

Add to `sandbox-file-browser.spec.ts` in the mocked test block:

```typescript
test('file preview opens as popup modal', async ({ page }) => {
  await page.goto('/sandbox/files/team1/sandbox-basic');
  await page.waitForLoadState('networkidle');

  const treeView = page.locator('[class*="pf-v5-c-tree-view"]').first();
  await expect(treeView).toBeVisible({ timeout: 10000 });

  // Click a file in the tree
  await page.getByText('main.py').click();

  // Modal should appear
  const modal = page.locator('[class*="pf-v5-c-modal-box"]');
  await expect(modal).toBeVisible({ timeout: 10000 });

  // Modal should show file content
  await expect(modal.getByText('def hello():')).toBeVisible();

  // Modal should have fullscreen button
  await expect(modal.getByRole('button', { name: /fullscreen/i })).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

Run: `npx playwright test e2e/sandbox-file-browser.spec.ts -g "file preview opens as popup" --reporter=list`
Expected: FAIL — no modal appears (current code uses inline preview)

**Step 3: Create FilePreviewModal component**

```tsx
// FilePreviewModal.tsx
import React, { useState } from 'react';
import { Modal, ModalVariant, Button, Split, SplitItem, Label, Tooltip } from '@patternfly/react-core';
import { ExpandIcon, CompressIcon, ExternalLinkAltIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { sandboxFileService } from '@/services/api';
import type { FileContent } from '@/types';
import { FilePreview } from './FilePreview';

interface FilePreviewModalProps {
  filePath: string | null;
  namespace: string;
  agentName: string;
  contextId?: string;
  isOpen: boolean;
  onClose: () => void;
}

export const FilePreviewModal: React.FC<FilePreviewModalProps> = ({
  filePath, namespace, agentName, contextId, isOpen, onClose,
}) => {
  const [isFullScreen, setIsFullScreen] = useState(false);

  const { data: fileContent, isLoading } = useQuery({
    queryKey: ['file-preview-modal', namespace, agentName, filePath],
    queryFn: () => sandboxFileService.getFileContent(namespace, agentName, filePath!),
    enabled: isOpen && !!filePath,
  });

  const fileName = filePath?.split('/').pop() || '';
  const browserPath = contextId
    ? `/sandbox/files/${namespace}/${agentName}/${contextId}`
    : `/sandbox/files/${namespace}/${agentName}`;

  return (
    <Modal
      variant={isFullScreen ? ModalVariant.default : ModalVariant.large}
      isOpen={isOpen}
      onClose={onClose}
      aria-label={`Preview ${fileName}`}
      title={fileName}
      className={isFullScreen ? 'pf-m-full-screen' : ''}
      actions={[
        <Tooltip key="fs" content={isFullScreen ? 'Exit fullscreen' : 'Fullscreen'}>
          <Button variant="plain" onClick={() => setIsFullScreen(!isFullScreen)}
            aria-label={isFullScreen ? 'Exit fullscreen' : 'Fullscreen'}>
            {isFullScreen ? <CompressIcon /> : <ExpandIcon />}
          </Button>
        </Tooltip>,
        <Link key="open" to={`${browserPath}?path=${encodeURIComponent(filePath || '')}`}>
          <Button variant="link" icon={<ExternalLinkAltIcon />}>
            Open in File Browser
          </Button>
        </Link>,
      ]}
    >
      <div style={{ minHeight: 300 }}>
        <FilePreview file={fileContent ?? null} isLoading={isLoading} />
      </div>
    </Modal>
  );
};
```

**Step 4: Update FileBrowser to use modal instead of inline preview**

In `FileBrowser.tsx`:
- Remove the right-panel split pane
- Add state: `const [previewPath, setPreviewPath] = useState<string | null>(null);`
- On tree click (file): `setPreviewPath(entry.path)` instead of `setSelectedFilePath`
- Render `<FilePreviewModal filePath={previewPath} isOpen={!!previewPath} onClose={() => setPreviewPath(null)} ... />`
- TreeView takes full width

**Step 5: Run test to verify it passes**

Run: `npx playwright test e2e/sandbox-file-browser.spec.ts -g "file preview opens as popup" --reporter=list`
Expected: PASS

**Step 6: Commit**

```bash
git add kagenti/ui-v2/src/components/FilePreviewModal.tsx kagenti/ui-v2/src/components/FileBrowser.tsx kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts
git commit -s -m "feat(ui): FilePreviewModal — universal popup with fullscreen toggle"
```

---

### Task 2: Add contextId to file browser route

**Files:**
- Modify: `kagenti/ui-v2/src/App.tsx:226-233`
- Modify: `kagenti/ui-v2/src/components/FileBrowser.tsx` (useParams, breadcrumb, title)
- Modify: `kagenti/backend/app/routers/sandbox_files.py` (new route, path enforcement)
- Test: `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts`

**Step 1: Write the failing test**

```typescript
test('session workspace shows context ID in breadcrumb and title', async ({ page }) => {
  // Mock: directory listing for a specific context workspace
  await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/ctx-abc123/**', async (route) => {
    await route.fulfill({ json: MOCK_DIR_LISTING });
  });

  await page.goto('/sandbox/files/team1/sandbox-basic/ctx-abc123');
  await page.waitForLoadState('networkidle');

  // Context ID should appear in the title
  await expect(page.getByText('ctx-abc123')).toBeVisible({ timeout: 10000 });

  // Breadcrumb should show workspace > ctx-abc123
  const breadcrumb = page.getByRole('navigation', { name: 'Breadcrumb' });
  await expect(breadcrumb).toContainText('workspace');
});
```

**Step 2: Run test to verify it fails**

Expected: FAIL — route doesn't match, 404

**Step 3: Add route to App.tsx**

Add before the existing `/sandbox/files/:namespace/:agentName` route:
```tsx
<Route
  path="/sandbox/files/:namespace/:agentName/:contextId"
  element={<ProtectedRoute><FileBrowser /></ProtectedRoute>}
/>
```

**Step 4: Update FileBrowser component**

- Extract `contextId` from `useParams`
- If `contextId` is present, set initial path to `/workspace/${contextId}`
- Update title to show `{agentName} — Session {contextId.slice(0,8)}...`
- Update `sandboxFileService` calls to use context-scoped API route when available

**Step 5: Add backend route**

In `sandbox_files.py`, add a new route:
```python
@router.get(
    "/{namespace}/files/{agent_name}/{context_id}",
    response_model=Union[DirectoryListing, FileContent],
)
async def get_context_files(
    namespace: str, agent_name: str, context_id: str,
    path: str = Query(default="/", description="Path relative to workspace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    # Enforce path within context workspace
    base = f"/workspace/{context_id}"
    full_path = posixpath.normpath(posixpath.join(base, path.lstrip("/")))
    if not full_path.startswith(base):
        raise HTTPException(status_code=400, detail="Path escapes context workspace")
    # ... reuse existing logic with full_path
```

**Step 6: Run test, commit**

---

### Task 3: FilePathCard for chat messages

**Files:**
- Create: `kagenti/ui-v2/src/components/FilePathCard.tsx`
- Modify: `kagenti/ui-v2/src/pages/SandboxPage.tsx:86-91` (replace linkifyFilePaths)
- Test: `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts`

**Step 1: Write the failing test**

```typescript
test('chat message with file path shows preview card', async ({ page }) => {
  // This test needs to mock the sandbox chat rendering with a file path
  // Mock the file browser API for the preview popup
  await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
    await route.fulfill({ json: MOCK_PY_CONTENT });
  });

  // Navigate to sandbox chat page and mock an agent message containing a file path
  // ... (setup SSE mock with tool_result containing file_write to /workspace/report.md)

  // FilePathCard should be visible
  await expect(page.getByText('report.md').first()).toBeVisible();

  // Hover should show tooltip
  await page.getByText('report.md').first().hover();
  await expect(page.getByText('Click for details')).toBeVisible({ timeout: 5000 });

  // Click should open FilePreviewModal
  await page.getByText('report.md').first().click();
  const modal = page.locator('[class*="pf-v5-c-modal-box"]');
  await expect(modal).toBeVisible({ timeout: 10000 });
});
```

**Step 2: Create FilePathCard component**

```tsx
// FilePathCard.tsx
import React, { useState } from 'react';
import { Label, Tooltip } from '@patternfly/react-core';
import { FileIcon } from '@patternfly/react-icons';
import { FilePreviewModal } from './FilePreviewModal';

interface FilePathCardProps {
  filePath: string;
  namespace: string;
  agentName: string;
  contextId?: string;
}

export const FilePathCard: React.FC<FilePathCardProps> = ({
  filePath, namespace, agentName, contextId,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const fileName = filePath.split('/').pop() || filePath;

  return (
    <>
      <Tooltip content="Click for details">
        <Label
          isCompact
          icon={<FileIcon />}
          onClick={() => setIsOpen(true)}
          style={{ cursor: 'pointer' }}
          render={({ className, content, componentRef }) => (
            <span ref={componentRef} className={className}>{content}</span>
          )}
        >
          {fileName}
        </Label>
      </Tooltip>
      <FilePreviewModal
        filePath={filePath}
        namespace={namespace}
        agentName={agentName}
        contextId={contextId}
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
      />
    </>
  );
};
```

**Step 3: Replace linkifyFilePaths in SandboxPage.tsx**

Replace the markdown-link approach (line 86-91) with a React component that renders `FilePathCard` inline for detected file paths. This requires changing the ReactMarkdown rendering to use a custom component for links or replacing the text preprocessing.

**Step 4: Run test, commit**

---

### Task 4: Parent folder navigation test

**Files:**
- Test: `kagenti/ui-v2/e2e/sandbox-file-browser.spec.ts`

**Step 1: Write the test**

```typescript
test('breadcrumb allows navigating back to parent folder', async ({ page }) => {
  // Mock nested directory
  await page.route('**/api/v1/sandbox/team1/files/sandbox-basic/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get('path') || '/workspace';
    if (path === '/workspace/src') {
      await route.fulfill({ json: {
        path: '/workspace/src',
        entries: [{ name: 'index.ts', path: '/workspace/src/index.ts', type: 'file', size: 100, modified: '2026-03-02T10:00:00+00:00', permissions: '-rw-r--r--' }],
      }});
    } else {
      await route.fulfill({ json: MOCK_DIR_LISTING });
    }
  });

  await page.goto('/sandbox/files/team1/sandbox-basic');
  await page.waitForLoadState('networkidle');

  // Click into src directory
  await page.getByText('src').click();
  await expect(page.getByText('index.ts')).toBeVisible({ timeout: 10000 });

  // Breadcrumb should show workspace > src
  const breadcrumb = page.getByRole('navigation', { name: 'Breadcrumb' });
  await expect(breadcrumb).toContainText('src');

  // Click workspace in breadcrumb to go back
  await breadcrumb.getByText('workspace').click();

  // Should be back at root listing
  await expect(page.getByText('README.md')).toBeVisible({ timeout: 10000 });
});
```

**Step 2: Run test — should already pass with existing breadcrumb implementation**

**Step 3: Commit**

---

### Task 5: Path traversal rejection test (backend)

**Files:**
- Test: `kagenti/backend/tests/test_sandbox_files.py` (or add to existing)
- Verify: `kagenti/backend/app/routers/sandbox_files.py`

**Step 1: Write the test**

```python
def test_context_path_traversal_rejected():
    """Paths escaping /workspace/{context_id}/ must be rejected."""
    # GET /sandbox/team1/files/sandbox-basic/ctx123?path=../../other-ctx/secret.txt
    # Expected: 400 Bad Request
```

**Step 2: Implement path enforcement in the context-scoped route**

**Step 3: Run test, commit**

---

### Task 6: Agent RCA report prompt

**Files:**
- Modify: `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/reasoning.py`

**Step 1: Update planner system prompt**

Add to `_PLANNER_SYSTEM` in `reasoning.py`:

```python
- For multi-step analysis, debugging, or investigation tasks, add a final
  step: "Write findings summary to report.md". Structure the report with
  sections: ## Problem, ## Investigation, ## Root Cause, ## Resolution.
```

**Step 2: Commit**

```bash
git commit -s -m "feat(sandbox): planner creates .md reports for complex analysis tasks"
```

---

### Task 7: Fix remaining 7 failing E2E tests

**Files:**
- Various spec files (sandbox.spec.ts, sandbox-sessions.spec.ts, sandbox-walkthrough.spec.ts, sandbox-file-browser.spec.ts)

**Step 1: Fix sandbox.spec.ts (3 failures)**
- Navigation timeouts — add explicit waits, increase timeouts, use more resilient selectors

**Step 2: Fix sandbox-walkthrough.spec.ts (1 failure)**
- Search box fill timeout — add waitFor before fill, handle PatternFly TextInput focus

**Step 3: Fix sandbox-sessions.spec.ts (1 failure)**
- Login timeout — increase timeout, add retry logic

**Step 4: Fix live file browser tests (2 failures)**
- Agent doesn't write files in time — increase timeout, add retry for file listing

**Step 5: Run all tests, verify all pass**

**Step 6: Commit**

---

## Execution Order

Tasks 1-4 are the core feature (popup + contextId + cards + navigation).
Task 5 is backend hardening.
Task 6 is prompt engineering.
Task 7 is test debt.

Recommend executing Tasks 1→2→3→4 sequentially (each builds on the previous), then 5-7 in parallel.
