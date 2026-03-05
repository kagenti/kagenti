// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useEffect, useRef, useCallback } from 'react';
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

// Initialize mermaid once at module level
mermaid.initialize({ startOnLoad: false, theme: 'default' });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleString();
  } catch {
    return dateStr;
  }
}

const BINARY_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg',
  '.zip', '.gz', '.tar', '.bz2', '.xz', '.7z', '.rar',
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.pyc', '.class',
  '.wasm', '.db', '.sqlite', '.sqlite3',
  '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
  '.ttf', '.otf', '.woff', '.woff2', '.eot',
]);

function isBinaryFile(path: string): boolean {
  const lower = path.toLowerCase();
  const dotIdx = lower.lastIndexOf('.');
  if (dotIdx === -1) return false;
  return BINARY_EXTENSIONS.has(lower.slice(dotIdx));
}

function looksLikeBinaryContent(content: string): boolean {
  // Check first 512 chars for null bytes or high ratio of non-printable chars
  const sample = content.slice(0, 512);
  if (sample.includes('\0')) return true;
  let nonPrintable = 0;
  for (let i = 0; i < sample.length; i++) {
    const code = sample.charCodeAt(i);
    if (code < 32 && code !== 9 && code !== 10 && code !== 13) nonPrintable++;
  }
  return sample.length > 0 && nonPrintable / sample.length > 0.1;
}

// ---------------------------------------------------------------------------
// MermaidBlock — renders a mermaid diagram from a code string
// ---------------------------------------------------------------------------

let mermaidCounter = 0;

const MermaidBlock: React.FC<{ chart: string }> = ({ chart }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const renderChart = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      const id = `mermaid-block-${++mermaidCounter}`;
      const { svg } = await mermaid.render(id, chart);
      if (containerRef.current) {
        containerRef.current.innerHTML = svg;
      }
    } catch {
      if (containerRef.current) {
        containerRef.current.textContent = 'Failed to render mermaid diagram';
      }
    }
  }, [chart]);

  useEffect(() => {
    renderChart();
  }, [renderChart]);

  return (
    <div
      ref={containerRef}
      style={{ display: 'flex', justifyContent: 'center', padding: '16px 0' }}
    />
  );
};

// ---------------------------------------------------------------------------
// Markdown component overrides for ReactMarkdown
// ---------------------------------------------------------------------------

const markdownComponents: Record<string, React.ComponentType<any>> = {
  code({ className, children, ...rest }: any) {
    const codeString = String(children).replace(/\n$/, '');
    // Detect language from className set by remark (e.g. "language-mermaid")
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : undefined;

    if (language === 'mermaid') {
      return <MermaidBlock chart={codeString} />;
    }

    // Fenced code block (has className / language)
    if (className) {
      return (
        <CodeBlock>
          <CodeBlockCode {...rest}>{codeString}</CodeBlockCode>
        </CodeBlock>
      );
    }

    // Inline code
    return <code className={className} {...rest}>{children}</code>;
  },
};

// ---------------------------------------------------------------------------
// FilePreview component
// ---------------------------------------------------------------------------

interface FilePreviewProps {
  file: FileContent | null;
  isLoading: boolean;
}

export const FilePreview: React.FC<FilePreviewProps> = ({ file, isLoading }) => {
  // Loading state
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Spinner size="lg" />
      </div>
    );
  }

  // Empty / nothing selected
  if (!file) {
    return (
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
    );
  }

  const fileName = file.path.split('/').pop() || file.path;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Metadata bar */}
      <div
        style={{
          padding: '8px 16px',
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
              {fileName}
            </Title>
          </SplitItem>
          <SplitItem isFilled />
          <SplitItem>
            <Label isCompact>{formatSize(file.size)}</Label>
          </SplitItem>
          <SplitItem>
            <Label isCompact color="blue">
              {formatDate(file.modified)}
            </Label>
          </SplitItem>
        </Split>
      </div>

      {/* File content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px' }}>
        {isBinaryFile(file.path) || looksLikeBinaryContent(file.content) ? (
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              height: '100%',
              color: 'var(--pf-v5-global--Color--200)',
            }}
          >
            Binary file — preview not available
          </div>
        ) : isMarkdown(file.path) ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {file.content}
          </ReactMarkdown>
        ) : (
          <CodeBlock>
            <CodeBlockCode>{file.content}</CodeBlockCode>
          </CodeBlock>
        )}
      </div>
    </div>
  );
};

export default FilePreview;
