// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { Component, useState, useMemo } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  PageSection,
  Spinner,
  TreeView,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Title,
  Alert,
} from '@patternfly/react-core';
import type { TreeViewDataItem } from '@patternfly/react-core';
import {
  FolderIcon,
  FileCodeIcon,
  FileIcon,
  LockIcon,
  ExclamationCircleIcon,
  CubesIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { sandboxFileService, ApiError } from '@/services/api';
import type { FileEntry } from '@/types';
import { FilePreview } from './FilePreview';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CODE_EXTENSIONS = new Set([
  '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.rb',
  '.sh', '.bash', '.zsh', '.yaml', '.yml', '.json', '.toml', '.xml',
  '.html', '.css', '.scss', '.sql', '.c', '.cpp', '.h', '.hpp',
  '.md', '.mdx', '.markdown', '.dockerfile', '.tf', '.hcl',
]);

function isCodeFile(name: string): boolean {
  const lower = name.toLowerCase();
  const dotIdx = lower.lastIndexOf('.');
  if (dotIdx === -1) return false;
  return CODE_EXTENSIONS.has(lower.slice(dotIdx));
}

function iconForEntry(entry: FileEntry): React.ReactNode {
  if (entry.type === 'directory') return <FolderIcon />;
  if (isCodeFile(entry.name)) return <FileCodeIcon />;
  return <FileIcon />;
}

/**
 * Sort entries: directories first, then files; alphabetically within each group.
 */
function sortEntries(entries: FileEntry[]): FileEntry[] {
  return [...entries].sort((a, b) => {
    if (a.type === 'directory' && b.type !== 'directory') return -1;
    if (a.type !== 'directory' && b.type === 'directory') return 1;
    return a.name.localeCompare(b.name);
  });
}

/**
 * Build path segments for breadcrumb from an absolute path.
 * e.g. "/workspace/src/lib" => ["/workspace", "/workspace/src", "/workspace/src/lib"]
 */
function pathSegments(path: string): Array<{ label: string; fullPath: string }> {
  const parts = path.split('/').filter(Boolean);
  const segments: Array<{ label: string; fullPath: string }> = [];
  let accumulated = '';
  for (const part of parts) {
    accumulated += '/' + part;
    segments.push({ label: part, fullPath: accumulated });
  }
  return segments;
}

// ---------------------------------------------------------------------------
// ErrorBoundary for FilePreview — catches render crashes
// ---------------------------------------------------------------------------

interface PreviewErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class PreviewErrorBoundary extends Component<
  { children: ReactNode; onReset?: () => void },
  PreviewErrorBoundaryState
> {
  constructor(props: { children: ReactNode; onReset?: () => void }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): PreviewErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('FilePreview render error:', error, errorInfo);
  }

  componentDidUpdate(prevProps: { children: ReactNode }) {
    // Reset error state when children change (user selects a different file)
    if (this.state.hasError && prevProps.children !== this.props.children) {
      this.setState({ hasError: false, error: null });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            height: '100%',
            gap: '12px',
            color: 'var(--pf-v5-global--danger-color--100)',
          }}
        >
          <ExclamationCircleIcon style={{ fontSize: '2em' }} />
          <span>Failed to preview this file</span>
          <span style={{ color: 'var(--pf-v5-global--Color--200)', fontSize: '0.85em' }}>
            {this.state.error?.message || 'Unknown render error'}
          </span>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// FileBrowser component
// ---------------------------------------------------------------------------

export interface FileBrowserProps {
  /** Namespace — if omitted, reads from route params */
  namespace?: string;
  /** Agent name — if omitted, reads from route params */
  agentName?: string;
  /** Context/session ID for session-scoped file browsing */
  contextId?: string;
  /** When true, renders without PageSection wrapper and adjusts height for embedding */
  embedded?: boolean;
}

export const FileBrowser: React.FC<FileBrowserProps> = ({
  namespace: propNamespace,
  agentName: propAgentName,
  contextId: propContextId,
  embedded = false,
}) => {
  const routeParams = useParams<{
    namespace: string;
    agentName: string;
    contextId?: string;
  }>();
  const [searchParams] = useSearchParams();

  const namespace = propNamespace || routeParams.namespace;
  const agentName = propAgentName || routeParams.agentName;
  const contextId = propContextId || routeParams.contextId;

  // Initial path from URL ?path= parameter, defaults to /workspace (or / for context-scoped)
  const initialPath = searchParams.get('path') || (contextId ? '/' : '/workspace');
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  // Fetch directory listing
  const {
    data: dirListing,
    isLoading: isDirLoading,
    isError: isDirError,
    error: dirError,
  } = useQuery({
    queryKey: ['sandbox-files', namespace, agentName, contextId, currentPath],
    queryFn: () => sandboxFileService.listDirectory(namespace!, agentName!, currentPath, contextId),
    enabled: !!namespace && !!agentName,
    retry: (failureCount, error) => {
      // Don't retry auth errors or not-found errors
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
        return false;
      }
      return failureCount < 2;
    },
  });

  // Fetch file content when a file is selected
  const {
    data: fileContent,
    isLoading: isFileLoading,
    isError: isFileError,
    error: fileError,
  } = useQuery({
    queryKey: ['sandbox-file-content', namespace, agentName, contextId, selectedFilePath],
    queryFn: () => sandboxFileService.getFileContent(namespace!, agentName!, selectedFilePath!, contextId),
    enabled: !!namespace && !!agentName && !!selectedFilePath,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
        return false;
      }
      return failureCount < 2;
    },
  });

  // Build TreeView data from directory listing
  const treeData: TreeViewDataItem[] = useMemo(() => {
    if (!dirListing?.entries) return [];
    const sorted = sortEntries(dirListing.entries);
    return sorted.map((entry) => ({
      id: entry.path,
      name: entry.name,
      icon: iconForEntry(entry),
      // Directories get an empty children array so TreeView shows the expand chevron
      ...(entry.type === 'directory' ? { children: [] } : {}),
    }));
  }, [dirListing]);

  // Handle TreeView selection
  const handleSelect = (_event: React.MouseEvent, item: TreeViewDataItem) => {
    const entry = dirListing?.entries.find((e) => e.path === item.id);
    if (!entry) return;

    if (entry.type === 'directory') {
      setCurrentPath(entry.path);
      setSelectedFilePath(null);
    } else {
      setSelectedFilePath(entry.path);
    }
  };

  const Wrapper: React.FC<{ children: ReactNode }> = ({ children }) =>
    embedded ? <div style={{ height: '100%' }}>{children}</div> : <PageSection>{children}</PageSection>;

  // No agent selected
  if (!namespace || !agentName) {
    return (
      <Wrapper>
        <EmptyState>
          <EmptyStateHeader
            titleText="No agent selected"
            icon={<EmptyStateIcon icon={FileIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            Select an agent to browse its sandbox files.
          </EmptyStateBody>
        </EmptyState>
      </Wrapper>
    );
  }

  // --- Error states for the directory listing ---
  if (isDirError && dirError) {
    const status = dirError instanceof ApiError ? dirError.status : 0;
    const message = dirError instanceof Error ? dirError.message : 'Unknown error';

    // 401 / 403 — authentication or authorization problem
    if (status === 401 || status === 403) {
      return (
        <Wrapper>
          <EmptyState>
            <EmptyStateHeader
              titleText="Authentication required"
              icon={<EmptyStateIcon icon={LockIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              You do not have permission to browse files for this agent.
              Please check your credentials and try again.
            </EmptyStateBody>
          </EmptyState>
        </Wrapper>
      );
    }

    // 404 — agent pod not found
    if (status === 404) {
      // Distinguish "agent not found" from other 404s by checking the message
      const isAgentNotFound =
        /not found|no.*(pod|agent|sandbox)/i.test(message);
      return (
        <Wrapper>
          <EmptyState>
            <EmptyStateHeader
              titleText={isAgentNotFound ? 'Agent not found' : 'Unable to load files'}
              icon={
                <EmptyStateIcon
                  icon={isAgentNotFound ? CubesIcon : ExclamationCircleIcon}
                />
              }
              headingLevel="h4"
            />
            <EmptyStateBody>
              {isAgentNotFound
                ? `The agent "${agentName}" was not found in namespace "${namespace}". It may have been deleted or has not been created yet.`
                : message}
            </EmptyStateBody>
          </EmptyState>
        </Wrapper>
      );
    }

    // Any other error (500, network failure, etc.)
    return (
      <Wrapper>
        <EmptyState>
          <EmptyStateHeader
            titleText="Unable to load files"
            icon={<EmptyStateIcon icon={ExclamationCircleIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>{message}</EmptyStateBody>
        </EmptyState>
      </Wrapper>
    );
  }

  const segments = pathSegments(currentPath);
  const ContentWrapper: React.FC<{ children: ReactNode }> = ({ children }) =>
    embedded
      ? <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>{children}</div>
      : <PageSection padding={{ default: 'noPadding' }}>{children}</PageSection>;

  return (
    <ContentWrapper>
      {/* Breadcrumb bar */}
      <div
        style={{
          padding: '12px',
          borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
        }}
      >
        <Breadcrumb>
          {segments.map((seg, idx) => {
            const isLast = idx === segments.length - 1;
            return (
              <BreadcrumbItem
                key={seg.fullPath}
                isActive={isLast}
                onClick={
                  isLast
                    ? undefined
                    : () => {
                        setCurrentPath(seg.fullPath);
                        setSelectedFilePath(null);
                      }
                }
                style={isLast ? undefined : { cursor: 'pointer' }}
              >
                {seg.label}
              </BreadcrumbItem>
            );
          })}
        </Breadcrumb>
      </div>

      {/* Title */}
      <div style={{ padding: '12px 12px 0 12px' }}>
        <Title headingLevel="h2" size="lg">
          {agentName} &mdash; File Browser
        </Title>
      </div>

      {/* File content error alert (non-fatal — only affects the preview pane) */}
      {isFileError && fileError && (
        <div style={{ padding: '12px' }}>
          <Alert variant="danger" title="Failed to load file" isInline>
            {fileError instanceof Error ? fileError.message : 'Unknown error'}
          </Alert>
        </div>
      )}

      {/* Split pane */}
      <div
        style={{
          display: 'flex',
          height: embedded ? '100%' : 'calc(100vh - 160px)',
          flex: embedded ? 1 : undefined,
          minHeight: 0,
        }}
      >
        {/* Left panel — directory tree */}
        <div
          style={{
            width: 320,
            borderRight: '1px solid var(--pf-v5-global--BorderColor--100)',
            overflow: 'auto',
            padding: '8px',
            flexShrink: 0,
          }}
        >
          {isDirLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 32 }}>
              <Spinner size="lg" />
            </div>
          ) : treeData.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--pf-v5-global--Color--200)', textAlign: 'center' }}>
              No files in this directory
            </div>
          ) : (
            <TreeView
              data={treeData}
              onSelect={handleSelect}
              hasGuides
              aria-label="File tree"
            />
          )}
        </div>

        {/* Right panel — file preview (wrapped in ErrorBoundary) */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <PreviewErrorBoundary key={selectedFilePath}>
            <FilePreview file={fileContent ?? null} isLoading={isFileLoading} />
          </PreviewErrorBoundary>
        </div>
      </div>
    </ContentWrapper>
  );
};

export default FileBrowser;
