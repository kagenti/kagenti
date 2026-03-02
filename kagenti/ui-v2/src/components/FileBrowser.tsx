// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
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
import { FolderIcon, FileCodeIcon, FileIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { sandboxFileService } from '@/services/api';
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
// FileBrowser component
// ---------------------------------------------------------------------------

export const FileBrowser: React.FC = () => {
  const { namespace, agentName } = useParams<{ namespace: string; agentName: string }>();

  const [currentPath, setCurrentPath] = useState('/');
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  // Fetch directory listing
  const {
    data: dirListing,
    isLoading: isDirLoading,
    error: dirError,
  } = useQuery({
    queryKey: ['sandbox-files', namespace, agentName, currentPath],
    queryFn: () => sandboxFileService.listDirectory(namespace!, agentName!, currentPath),
    enabled: !!namespace && !!agentName,
  });

  // Fetch file content when a file is selected
  const {
    data: fileContent,
    isLoading: isFileLoading,
  } = useQuery({
    queryKey: ['sandbox-file-content', namespace, agentName, selectedFilePath],
    queryFn: () => sandboxFileService.getFileContent(namespace!, agentName!, selectedFilePath!),
    enabled: !!namespace && !!agentName && !!selectedFilePath,
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

  // No agent selected
  if (!namespace || !agentName) {
    return (
      <PageSection>
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
      </PageSection>
    );
  }

  const segments = pathSegments(currentPath);

  return (
    <PageSection padding={{ default: 'noPadding' }}>
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

      {/* Error alert */}
      {dirError && (
        <div style={{ padding: '12px' }}>
          <Alert variant="danger" title="Failed to load directory" isInline>
            {dirError instanceof Error ? dirError.message : 'Unknown error'}
          </Alert>
        </div>
      )}

      {/* Split pane */}
      <div
        style={{
          display: 'flex',
          height: 'calc(100vh - 160px)',
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
          ) : (
            <TreeView
              data={treeData}
              onSelect={handleSelect}
              hasGuides
              aria-label="File tree"
            />
          )}
        </div>

        {/* Right panel — file preview */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <FilePreview file={fileContent ?? null} isLoading={isFileLoading} />
        </div>
      </div>
    </PageSection>
  );
};

export default FileBrowser;
