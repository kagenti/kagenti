// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import {
  TreeView,
  TreeViewDataItem,
  Card,
  CardBody,
  CardTitle,
  Split,
  SplitItem,
  CodeBlock,
  CodeBlockCode,
  Label,
  Title,
} from '@patternfly/react-core';
import { FileIcon, FolderIcon } from '@patternfly/react-icons';
import type { SkillFile } from '@/types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface SkillFileTreeProps {
  files: SkillFile[];
  onFileSelect?: (file: SkillFile) => void;
  showPreview?: boolean;
}

interface TreeNode {
  name: string;
  path: string;
  children?: TreeNode[];
  file?: SkillFile;
  isDirectory: boolean;
}

/**
 * Build a tree structure from flat file list
 */
function buildFileTree(files: SkillFile[]): TreeNode[] {
  const root: TreeNode = {
    name: '',
    path: '',
    children: [],
    isDirectory: true,
  };

  files.forEach((file) => {
    const parts = file.path.split('/');
    let current = root;

    parts.forEach((part, index) => {
      const isLastPart = index === parts.length - 1;
      const currentPath = parts.slice(0, index + 1).join('/');

      if (!current.children) {
        current.children = [];
      }

      let child = current.children.find((c) => c.name === part);

      if (!child) {
        child = {
          name: part,
          path: currentPath,
          isDirectory: !isLastPart,
          children: isLastPart ? undefined : [],
          file: isLastPart ? file : undefined,
        };
        current.children.push(child);
      }

      current = child;
    });
  });

  return root.children || [];
}

/**
 * Convert tree nodes to PatternFly TreeView format
 */
function convertToTreeViewData(nodes: TreeNode[]): TreeViewDataItem[] {
  return nodes.map((node) => {
    const item: TreeViewDataItem = {
      name: node.name,
      id: node.path,
      icon: node.isDirectory ? <FolderIcon /> : <FileIcon />,
      defaultExpanded: node.name === 'SKILL.md' || node.isDirectory,
    };

    if (node.children && node.children.length > 0) {
      item.children = convertToTreeViewData(node.children);
    }

    return item;
  });
}

/**
 * Find file by path in tree
 */
function findFileByPath(nodes: TreeNode[], path: string): SkillFile | undefined {
  for (const node of nodes) {
    if (node.path === path && node.file) {
      return node.file;
    }
    if (node.children) {
      const found = findFileByPath(node.children, path);
      if (found) return found;
    }
  }
  return undefined;
}

const MARKDOWN_EXTENSIONS = ['.md', '.mdx', '.markdown'];

function isMarkdown(path: string): boolean {
  const lower = path.toLowerCase();
  return MARKDOWN_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export const SkillFileTree: React.FC<SkillFileTreeProps> = ({
  files,
  onFileSelect,
  showPreview = true
}) => {
  const [selectedFile, setSelectedFile] = useState<SkillFile | null>(null);

  const tree = React.useMemo(() => buildFileTree(files), [files]);
  const treeData = React.useMemo(() => convertToTreeViewData(tree), [tree]);

  const handleSelect = (_event: React.MouseEvent, item: TreeViewDataItem) => {
    const file = findFileByPath(tree, item.id as string);
    if (file) {
      setSelectedFile(file);
      onFileSelect?.(file);
    }
  };

  if (!showPreview) {
    // Legacy mode: just show the tree in a card
    return (
      <Card>
        <CardTitle>
          <Split hasGutter>
            <SplitItem isFilled>Skill Files ({files.length})</SplitItem>
          </Split>
        </CardTitle>
        <CardBody>
          {files.length === 0 ? (
            <p>No files in this skill</p>
          ) : (
            <TreeView
              data={treeData}
              onSelect={handleSelect}
              hasGuides
              allExpanded={false}
            />
          )}
        </CardBody>
      </Card>
    );
  }

  // Split-pane mode: tree on left, preview on right
  return (
    <div style={{ display: 'flex', gap: '1rem', height: 'calc(100vh - 300px)', minHeight: '500px' }}>
      {/* Left pane: File tree */}
      <Card style={{ flex: '0 0 350px', overflow: 'auto' }}>
        <CardTitle>
          <Split hasGutter>
            <SplitItem isFilled>Files ({files.length})</SplitItem>
          </Split>
        </CardTitle>
        <CardBody>
          {files.length === 0 ? (
            <p>No files in this skill</p>
          ) : (
            <TreeView
              data={treeData}
              onSelect={handleSelect}
              hasGuides
              allExpanded={false}
            />
          )}
        </CardBody>
      </Card>

      {/* Right pane: File preview */}
      <Card style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {selectedFile ? (
          <>
            {/* File header */}
            <div
              style={{
                padding: '1rem',
                borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
                backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                flexShrink: 0,
              }}
            >
              <Split hasGutter>
                <SplitItem>
                  <FileIcon style={{ marginRight: 6, verticalAlign: 'middle' }} />
                </SplitItem>
                <SplitItem>
                  <Title headingLevel="h4" size="md" style={{ display: 'inline' }}>
                    {selectedFile.name}
                  </Title>
                </SplitItem>
                <SplitItem isFilled />
                <SplitItem>
                  <Label isCompact>{formatSize(selectedFile.size)}</Label>
                </SplitItem>
              </Split>
              <div style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: 'var(--pf-v5-global--Color--200)' }}>
                {selectedFile.path}
              </div>
            </div>

            {/* File content */}
            <CardBody style={{ flex: 1, overflow: 'auto' }}>
              {isMarkdown(selectedFile.path) ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {selectedFile.content}
                </ReactMarkdown>
              ) : (
                <CodeBlock>
                  <CodeBlockCode>{selectedFile.content}</CodeBlockCode>
                </CodeBlock>
              )}
            </CardBody>
          </>
        ) : (
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              height: '100%',
              color: 'var(--pf-v5-global--Color--200)',
            }}
          >
            Select a file to preview
          </div>
        )}
      </Card>
    </div>
  );
};

