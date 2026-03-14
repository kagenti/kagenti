// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  PageSection,
  Card,
  CardBody,
  TextArea,
  Button,
  Split,
  SplitItem,
  Spinner,
  Alert,
  Label,
  Tooltip,
  Modal,
  ModalVariant,
} from '@patternfly/react-core';
import { PaperPlaneIcon, UserIcon, RobotIcon, FileIcon, ShieldAltIcon, CogIcon, StopCircleIcon } from '@patternfly/react-icons';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useQuery } from '@tanstack/react-query';
import { sandboxService } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { SessionSidebar } from '../components/SessionSidebar';
import { SkillWhisperer } from '../components/SkillWhisperer';
// SandboxConfig disabled — model/repo/branch not yet wired to backend
// import { SandboxConfig, SandboxConfigValues } from '../components/SandboxConfig';
// NamespaceSelector removed from session view — namespace shown as read-only Label
// import { NamespaceSelector } from '../components/NamespaceSelector';
import { DelegationCard, type DelegationState } from '../components/DelegationCard';
import { HitlApprovalCard } from '../components/HitlApprovalCard';
import { AgentLoopCard } from '../components/AgentLoopCard';
import { SimpleLoopCard } from '../components/SimpleLoopCard';
import { GraphLoopView } from '../components/GraphLoopView';
import { FloatingViewBar, type ViewMode, isValidViewMode } from '../components/FloatingViewBar';
import { FilePreviewModal } from '../components/FilePreviewModal';
import { SessionStatsPanel } from '../components/SessionStatsPanel';
import { LlmUsagePanel } from '../components/LlmUsagePanel';
import { FileBrowser } from '../components/FileBrowser';
import { PodStatusPanel } from '../components/PodStatusPanel';
import { SidecarPanel } from '../components/SidecarTab';
import { ModelSwitcher } from '../components/ModelSwitcher';
import { SandboxWizard } from '../components/SandboxWizard';
import { SubSessionsPanel, useChildSessionCount } from '../components/SubSessionsPanel';
import { sidecarService, type SidecarInfo } from '../services/api';
import type { AgentLoop } from '../types/agentLoop';
import { applyLoopEvent, buildAgentLoops, createDefaultAgentLoop, type LoopEvent } from '../utils/loopBuilder';

const DELEGATION_EVENT_TYPES = ['delegation_start', 'delegation_progress', 'delegation_complete'] as const;
type DelegationEventType = typeof DELEGATION_EVENT_TYPES[number];

interface ToolCallData {
  type: 'tool_call' | 'tool_result' | 'thinking' | 'llm_response' | 'error' | 'hitl_request' | DelegationEventType;
  name?: string;
  args?: string | Record<string, unknown>;
  output?: string;
  content?: string;
  message?: string;
  command?: string;
  reason?: string;
  tools?: Array<{ name: string; args: string | Record<string, unknown> }>;
  // Delegation fields
  child_context_id?: string;
  delegation_mode?: string;
  task?: string;
  variant?: string;
  state?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolData?: ToolCallData;
  username?: string;
  /** Stable sort key from the backend (_index) or insertion order. */
  order: number;
}

/** Number of history messages to show initially; rest behind "Load earlier". */
const INITIAL_HISTORY_LIMIT = 30;

/** Format timestamp for display — HH:mm:ss.mmm for precise ordering. */
function formatMsgTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${h}:${m}:${s}.${ms}`;
}

/** Detect and filter out LangGraph intermediate status dumps and JSON loop events from history. */
function isGraphDump(text: string): boolean {
  const t = text.trim();
  // Old-style graph dumps: "assistant: {...}", "tools: {...}", "__end__: {...}"
  if (/^(assistant|tools|__end__):\s/m.test(t)) return true;
  // New-style JSON loop events stored as message text
  try {
    const parsed = JSON.parse(t);
    if (parsed && typeof parsed === 'object' && parsed.type && parsed.loop_id) return true;
  } catch { /* not JSON */ }
  return false;
}

/** Regex matching absolute file paths in agent output. */
const FILE_PATH_RE = /(?<!\w)(\/(?:workspace|data|repos|app|home|tmp|opt|var|srv)\/[\w./_-]+(?:\.\w+)?)/g;

/**
 * Convert file paths in text to markdown links pointing to the file browser.
 * Skips paths that are already inside backticks (those are handled by the
 * custom `code` component in buildMarkdownComponents).
 */
function linkifyFilePaths(text: string, namespace: string, agentName: string): string {
  // Split text by backtick-delimited sections to avoid double-processing
  const parts = text.split(/(`[^`]+`)/g);
  return parts
    .map((part, i) => {
      // Odd indices are backtick-wrapped — leave them alone
      if (i % 2 === 1) return part;
      // Even indices are plain text — linkify paths
      return part.replace(FILE_PATH_RE, (match) =>
        `[${match}](/sandbox/files/${namespace}/${agentName}?path=${encodeURIComponent(match)})`
      );
    })
    .join('');
}

/** Inline file path card that renders as a clickable Label with file preview modal. */
const FilePathCard: React.FC<{ path: string; namespace: string; agentName: string }> = ({ path, namespace, agentName }) => {
  const [showModal, setShowModal] = useState(false);
  const fileName = path.split('/').pop() || path;

  return (
    <>
      <Tooltip content="Click for details">
        <Label isCompact icon={<FileIcon />} onClick={() => setShowModal(true)} style={{ cursor: 'pointer', margin: '0 2px' }}>
          {fileName}
        </Label>
      </Tooltip>
      <FilePreviewModal
        filePath={path}
        namespace={namespace}
        agentName={agentName}
        isOpen={showModal}
        onClose={() => setShowModal(false)}
      />
    </>
  );
};

/** Build custom ReactMarkdown components that render file browser links as FilePathCard. */
function buildMarkdownComponents(namespace: string, agentName: string) {
  return {
    a: ({ href, children }: any) => {
      // If it's a file browser link, render FilePathCard
      if (href?.startsWith('/sandbox/files/')) {
        const pathMatch = href.match(/path=([^&]+)/);
        const filePath = pathMatch ? decodeURIComponent(pathMatch[1]) : '';
        return <FilePathCard path={filePath} namespace={namespace} agentName={agentName} />;
      }
      // Regular link
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    },
    // Inline code that contains a file path → render as FilePathCard
    code: ({ children, className }: any) => {
      // Only handle inline code (no className means no language = not a code block)
      if (className) {
        return <code className={className}>{children}</code>;
      }
      const text = String(children).trim();
      if (FILE_PATH_RE.test(text)) {
        // Reset lastIndex since FILE_PATH_RE is global
        FILE_PATH_RE.lastIndex = 0;
        return <FilePathCard path={text} namespace={namespace} agentName={agentName} />;
      }
      FILE_PATH_RE.lastIndex = 0;
      return <code>{children}</code>;
    },
  };
}

/**
 * Parse a graph event line — JSON first, regex fallback for old Python repr.
 * Mirrors the backend's _parse_graph_event() logic so tool calls render
 * during streaming even when the LangGraphSerializer isn't deployed.
 */
function parseGraphEvent(text: string): ToolCallData | null {
  const stripped = text.trim();
  if (!stripped) return null;

  // New format: structured JSON
  try {
    const data = JSON.parse(stripped);
    if (data && typeof data === 'object' && data.type) {
      return data as ToolCallData;
    }
  } catch {
    // Not JSON — try regex fallback
  }

  // Old format: Python repr — "assistant: {'messages': [AIMessage(...)]}"
  if (stripped.startsWith('assistant:')) {
    if (stripped.includes('tool_calls=') || (stripped.includes("'name':") && stripped.includes("'args':"))) {
      const calls = [...stripped.matchAll(/'name':\s*'([^']+)'.*?'args':\s*(\{[^}]*\}?)/g)];
      if (calls.length > 0) {
        return {
          type: 'tool_call',
          tools: calls.map(c => ({ name: c[1], args: c[2] })),
        };
      }
    }
    // Extract content
    const contentMatch = stripped.match(/content='((?:[^'\\]|\\.){1,2000})'/) ||
                         stripped.match(/content="((?:[^"\\]|\\.){1,2000})"/) ||
                         stripped.match(/content='([^']{1,500})/);
    if (contentMatch && contentMatch[1].trim()) {
      return { type: 'llm_response', content: contentMatch[1].slice(0, 2000) };
    }
  } else if (stripped.startsWith('tools:')) {
    // Extract tool result
    const patterns = [
      /content='((?:[^'\\]|\\.)*?)'\s*,\s*name='([^']*)'/,
      /content="((?:[^"\\]|\\.)*?)"\s*,\s*name='([^']*)'/,
      /content='((?:[^'\\]|\\.)*?)'\s*,\s*name="([^"]*)"/,
      /content="((?:[^"\\]|\\.)*?)"\s*,\s*name="([^"]*)"/,
    ];
    for (const pattern of patterns) {
      const match = stripped.match(pattern);
      if (match) {
        return {
          type: 'tool_result',
          name: match[2],
          output: match[1].slice(0, 2000).replace(/\\n/g, '\n'),
        };
      }
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Message bubble component
// ---------------------------------------------------------------------------

/** Expandable tool call step in the conversation. */
const ToolCallStep: React.FC<{
  data: ToolCallData;
  onApprove?: () => void;
  onDeny?: () => void;
}> = ({ data, onApprove, onDeny }) => {
  const [expanded, setExpanded] = useState(false);

  if (data.type === 'tool_call') {
    return (
      <div
        data-testid="tool-call-step"
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--info-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{ fontWeight: 600 }}>
          {expanded ? '▼' : '▶'} Tool Call:{' '}
          {(() => {
            if (!data.tools || data.tools.length === 0) return 'unknown';
            const counts = data.tools.reduce((acc, t) => {
              const name = t.name || 'unknown';
              acc[name] = (acc[name] || 0) + 1;
              return acc;
            }, {} as Record<string, number>);
            return Object.entries(counts)
              .map(([name, count]) => count > 1 ? `${name} (${count})` : name)
              .join(', ');
          })()}
        </div>
        {expanded &&
          data.tools?.map((t, i) => (
            <pre
              key={i}
              style={{
                margin: '4px 0',
                padding: 8,
                backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
                color: 'var(--pf-v5-global--Color--light-100)',
                borderRadius: 4,
                fontSize: '0.9em',
                overflow: 'auto',
              }}
            >
              {t.name}({typeof t.args === 'string' ? t.args : JSON.stringify(t.args, null, 2)})
            </pre>
          ))}
      </div>
    );
  }

  if (data.type === 'tool_result') {
    return (
      <div
        data-testid="tool-result-step"
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--success-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{ fontWeight: 600 }}>
          {expanded ? '▼' : '▶'} Result: {data.name || 'tool'}
        </div>
        {expanded && (
          <pre
            style={{
              margin: '4px 0',
              padding: 8,
              backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
              color: 'var(--pf-v5-global--Color--light-100)',
              borderRadius: 4,
              fontSize: '0.9em',
              overflow: 'auto',
              maxHeight: 200,
            }}
          >
            {data.output || '(no output)'}
          </pre>
        )}
      </div>
    );
  }

  if (data.type === 'thinking' || data.type === 'llm_response') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '4px 10px',
          fontSize: '0.82em',
          fontStyle: 'italic',
          color: 'var(--pf-v5-global--Color--200)',
        }}
      >
        {data.content}
      </div>
    );
  }

  if (data.type === 'error') {
    return (
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--danger-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--pf-v5-global--danger-color--100)' }}>
          Error
        </div>
        <pre style={{ margin: '4px 0', padding: 8, fontSize: '0.9em', overflow: 'auto', maxHeight: 150 }}>
          {data.message || '(unknown error)'}
        </pre>
      </div>
    );
  }

  if (data.type === 'hitl_request') {
    return (
      <HitlApprovalCard
        command={data.command || ''}
        reason={data.reason || 'Agent requests approval'}
        onApprove={onApprove}
        onReject={onDeny}
      />
    );
  }

  // Delegation events — render DelegationCard inline
  if (DELEGATION_EVENT_TYPES.includes(data.type as DelegationEventType)) {
    const delegationState: DelegationState = {
      childId: data.child_context_id || '',
      mode: data.delegation_mode || 'in-process',
      task: data.task || data.message || '',
      variant: data.variant || 'sandbox-legion',
      status: data.type === 'delegation_complete'
        ? (data.state === 'COMPLETED' ? 'completed' : 'failed')
        : data.type === 'delegation_progress' ? 'working' : 'spawning',
    };
    return <DelegationCard delegation={delegationState} result={data.content} />;
  }

  return null;
};

const ChatBubble: React.FC<{
  msg: Message;
  currentUsername?: string;
  namespace: string;
  agentName: string;
  onApprove?: () => void;
  onDeny?: () => void;
}> = ({ msg, currentUsername, namespace, agentName, onApprove, onDeny }) => {
  const isUser = msg.role === 'user';

  // Tool call/result steps render as compact expandable items
  if (!isUser && msg.toolData) {
    return <ToolCallStep data={msg.toolData} onApprove={onApprove} onDeny={onDeny} />;
  }

  // Display name: show actual username with (you) suffix for own messages
  const displayName = isUser
    ? (msg.username
        ? (msg.username === currentUsername ? `${msg.username} (you)` : msg.username)
        : 'You')
    : 'Agent';

  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 14px',
        marginBottom: 4,
        borderRadius: 8,
        backgroundColor: isUser
          ? 'var(--pf-v5-global--BackgroundColor--200)'
          : 'var(--pf-v5-global--BackgroundColor--100)',
        border: isUser
          ? 'none'
          : '1px solid var(--pf-v5-global--BorderColor--100)',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          flexShrink: 0,
          width: 32,
          height: 32,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: isUser
            ? 'var(--pf-v5-global--primary-color--100)'
            : 'var(--pf-v5-global--success-color--100)',
          color: '#fff',
          fontSize: 14,
        }}
      >
        {isUser ? <UserIcon /> : <RobotIcon />}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Header row */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 4,
          }}
        >
          <span style={{ fontWeight: 600, fontSize: '0.9em' }} data-testid={`chat-sender-${msg.id}`}>
            {displayName}
          </span>
          <span
            style={{
              fontSize: '0.75em',
              color: 'var(--pf-v5-global--Color--200)',
              cursor: 'default',
            }}
            title={msg.timestamp.toISOString()}
          >
            {formatMsgTime(msg.timestamp)}
          </span>
        </div>

        {/* Body */}
        {isUser ? (
          <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{msg.content}</p>
        ) : (
          <div className="sandbox-markdown" style={{ fontSize: '0.92em' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(namespace, agentName)}>
              {linkifyFilePaths(msg.content, namespace, agentName)}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * Group messages into "turns" for collapsed rendering.
 * A turn is: one user message + all consecutive assistant messages after it.
 * The last text-content assistant message in a turn is the "final answer".
 * Everything else (tool calls, intermediate messages) goes behind a toggle.
 */
interface Turn {
  user?: Message;
  assistantMessages: Message[];
  finalAnswer: string;
}

function groupMessagesIntoTurns(messages: Message[]): Turn[] {
  // Sort by the stable `order` field (backend _index or insertion position).
  // This is necessary because messages from polling, SSE, and history loads
  // may be merged in non-chronological order.
  const sorted = [...messages].sort((a, b) => a.order - b.order);
  const turns: Turn[] = [];
  let current: Turn = { assistantMessages: [], finalAnswer: '' };

  for (const msg of sorted) {
    if (msg.role === 'user') {
      // Start new turn
      if (current.user || current.assistantMessages.length > 0) {
        turns.push(current);
      }
      current = { user: msg, assistantMessages: [], finalAnswer: '' };
    } else {
      current.assistantMessages.push(msg);
      // Track last non-empty text content as the final answer
      if (msg.content && msg.content.trim() && !msg.toolData) {
        current.finalAnswer = msg.content;
      }
    }
  }
  if (current.user || current.assistantMessages.length > 0) {
    turns.push(current);
  }
  return turns;
}

/** Interactive event types that must ALWAYS be visible (not collapsed). */
const INTERACTIVE_TYPES = new Set(['hitl_request', 'delegation_start', 'delegation_progress', 'delegation_complete']);

/** Collapsed agent turn: final answer visible, intermediate steps behind toggle. */
const CollapsedTurn: React.FC<{
  turn: Turn;
  namespace: string;
  agentName: string;
  onApprove?: () => void;
  onDeny?: () => void;
}> = ({ turn, namespace, agentName, onApprove, onDeny }) => {
  const [expanded, setExpanded] = useState(false);

  // Split messages: interactive (always visible) vs collapsible (behind toggle)
  const interactive = turn.assistantMessages.filter(
    (m) => m.toolData && INTERACTIVE_TYPES.has(m.toolData.type)
  );
  const collapsible = turn.assistantMessages.filter(
    (m) =>
      // Must have content or tool data to be worth showing
      (m.content?.trim() || m.toolData) &&
      // Not the final answer (already shown above)
      (m.content !== turn.finalAnswer || m.toolData) &&
      // Not interactive events (shown outside toggle)
      !(m.toolData && INTERACTIVE_TYPES.has(m.toolData.type))
  );

  return (
    <div
      data-testid="collapsed-turn"
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 14px',
        marginBottom: 4,
        borderRadius: 8,
        border: '1px solid var(--pf-v5-global--success-color--100)',
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          flexShrink: 0,
          width: 32,
          height: 32,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'var(--pf-v5-global--success-color--100)',
          color: '#fff',
          fontSize: 14,
        }}
      >
        <RobotIcon />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Timestamp header */}
        {turn.assistantMessages.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: '0.9em' }}>{agentName || 'Agent'}</span>
            <span
              style={{ fontSize: '0.75em', color: 'var(--pf-v5-global--Color--200)', cursor: 'default' }}
              title={turn.assistantMessages[0].timestamp.toISOString()}
            >
              {formatMsgTime(turn.assistantMessages[0].timestamp)}
            </span>
          </div>
        )}
        {/* Final answer — always visible */}
        {turn.finalAnswer && (
          <div className="sandbox-markdown" style={{ fontSize: '0.92em', marginBottom: 6 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(namespace, agentName)}>
              {linkifyFilePaths(turn.finalAnswer, namespace, agentName)}
            </ReactMarkdown>
          </div>
        )}

        {/* Interactive events — ALWAYS visible (HITL approve/deny, delegation) */}
        {interactive.map((m) => (
          <div key={m.id} style={{ marginBottom: 4 }}>
            <ToolCallStep data={m.toolData!} onApprove={onApprove} onDeny={onDeny} />
          </div>
        ))}

        {/* Collapsible steps toggle */}
        {collapsible.length > 0 && (
          <>
            <div
              onClick={() => setExpanded((prev) => !prev)}
              data-testid="turn-details-toggle"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                borderRadius: 4,
                border: '1px solid var(--pf-v5-global--BorderColor--100)',
                fontSize: '0.8em',
                fontWeight: 500,
                color: 'var(--pf-v5-global--Color--200)',
                cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              {expanded ? '\u25bc' : '\u25b6'} {collapsible.length} step{collapsible.length !== 1 ? 's' : ''}
            </div>

            {expanded && (
              <div style={{ marginTop: 8, paddingLeft: 8, borderLeft: '2px solid var(--pf-v5-global--BorderColor--100)', maxHeight: 400, overflowY: 'auto' }}>
                {collapsible.map((m) => (
                  <div key={m.id} style={{ marginBottom: 4, fontSize: '0.85em' }}>
                    {m.toolData ? (
                      <ToolCallStep data={m.toolData} onApprove={onApprove} onDeny={onDeny} />
                    ) : m.content ? (
                      <div className="sandbox-markdown" style={{ color: 'var(--pf-v5-global--Color--200)' }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(namespace, agentName)}>
                          {linkifyFilePaths(m.content, namespace, agentName)}
                        </ReactMarkdown>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// SandboxPage
// ---------------------------------------------------------------------------

const STORAGE_KEY_SESSION = 'kagenti-sandbox-last-session';
const STORAGE_KEY_NAMESPACE = 'kagenti-sandbox-last-namespace';
const STORAGE_KEY_AGENT_PREFIX = 'kagenti-sandbox-agent:'; // keyed by session id

/**
 * Determine initial session ID.
 *
 * Priority: URL ?session= param > localStorage (only if URL has no param
 * and the page was just reloaded, not a fresh navigation).
 */
function getInitialSession(params: URLSearchParams): string {
  const fromUrl = params.get('session');
  if (fromUrl) return fromUrl;

  // Only restore from localStorage if this looks like a reload (referrer is same origin)
  // or if the navigation entry type is "reload".
  try {
    const navEntries = performance.getEntriesByType('navigation');
    const isReload =
      navEntries.length > 0 &&
      (navEntries[0] as PerformanceNavigationTiming).type === 'reload';
    if (isReload) {
      return localStorage.getItem(STORAGE_KEY_SESSION) || '';
    }
  } catch {
    // fallback — don't restore
  }
  return '';
}

export const SandboxPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  // setNamespace removed — namespace is read-only during active session
  const [namespace] = useState(
    () =>
      localStorage.getItem(STORAGE_KEY_NAMESPACE) || 'team1'
  );
  const [contextId, setContextId] = useState(() =>
    getInitialSession(searchParams)
  );
  const [messages, setMessages] = useState<Message[]>([]);
  /** Auto-incrementing counter for message ordering.
   *  Starts at a high value so live messages always sort after history messages
   *  (which use backend _index values starting from 0). Reset when history loads. */
  const orderCounterRef = useRef(1_000_000);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [oldestIndex, setOldestIndex] = useState<number | null>(null);
  // Synchronous guard against double-send (React StrictMode double-invokes
  // effects/callbacks, and async setState batching means two rapid calls
  // can both see isStreaming===false before either sets it to true).
  const sendingRef = useRef(false);
  /** Last user message text — attached to the next AgentLoop created during streaming. */
  const lastUserMessageRef = useRef<string>('');
  const subscribeAbortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { getToken, user } = useAuth();
  const currentUsername = user?.username || 'you';
  const [selectedAgent, setSelectedAgent] = useState(() => {
    // Restore agent from URL param first, then localStorage keyed by session
    const urlAgent = searchParams.get('agent');
    if (urlAgent) return urlAgent;
    const sid = getInitialSession(searchParams);
    if (sid) {
      const stored = localStorage.getItem(STORAGE_KEY_AGENT_PREFIX + sid);
      if (stored) return stored;
    }
    return 'sandbox-legion';
  });
  // Refs mirror state for use in async closures (avoids stale state)
  const selectedAgentRef = useRef(selectedAgent);
  useEffect(() => { selectedAgentRef.current = selectedAgent; }, [selectedAgent]);
  const contextIdRef = useRef(contextId);
  useEffect(() => { contextIdRef.current = contextId; }, [contextId]);

  // Sync selectedAgent when URL ?agent= param changes (e.g. SPA navigation)
  useEffect(() => {
    const urlAgent = searchParams.get('agent');
    if (urlAgent && urlAgent !== selectedAgent) {
      selectedAgentRef.current = urlAgent; // Update ref immediately (no race)
      setSelectedAgent(urlAgent);
    }
  }, [searchParams]);
  const [agentLoops, setAgentLoops] = useState<Map<string, AgentLoop>>(new Map());
  const [skillWhispererDismissed, setSkillWhispererDismissed] = useState(false);
  const [sessionModelOverride, setSessionModelOverride] = useState<string>('');
  const [activeTab, setActiveTab] = useState<string>(() => searchParams.get('tab') || 'chat');
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    const param = searchParams.get('view');
    return isValidViewMode(param) ? param : 'advanced';
  });
  const handleViewModeChange = useCallback((mode: ViewMode) => {
    setViewMode(mode);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (mode === 'advanced') {
        next.delete('view');
      } else {
        next.set('view', mode);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const renderLoopCard = useCallback((loop: AgentLoop, streaming: boolean) => {
    if (viewMode === 'simple') return <SimpleLoopCard key={loop.id} loop={loop} />;
    if (viewMode === 'graph') return <GraphLoopView key={loop.id} loop={loop} />;
    return <AgentLoopCard key={loop.id} loop={loop} isStreaming={streaming} namespace={namespace} agentName={selectedAgent} />;
  }, [viewMode, namespace, selectedAgent]);

  // Keyboard shortcuts: Alt+1/2/3 for view modes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;
        if (e.key === '1') handleViewModeChange('simple');
        else if (e.key === '2') handleViewModeChange('advanced');
        else if (e.key === '3') handleViewModeChange('graph');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleViewModeChange]);

  // Child session count for sub-sessions tab badge
  const childSessionCount = useChildSessionCount(namespace, contextId);

  // Sidecar agents state
  const [sidecars, setSidecars] = useState<SidecarInfo[]>([]);
  const [reconfigureOpen, setReconfigureOpen] = useState(false);
  // Poll sidecars list when we have a contextId
  useEffect(() => {
    if (!contextId || !namespace) return;
    const poll = async () => {
      try {
        const list = await sidecarService.list(namespace, contextId);
        setSidecars(list);
      } catch {
        // Sidecar API not available — ignore
      }
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [contextId, namespace]);

  const handleSidecarToggleEnable = async (sidecarType: string, enabled: boolean) => {
    if (!contextId || !namespace) return;
    try {
      if (enabled) {
        await sidecarService.enable(namespace, contextId, sidecarType);
      } else {
        await sidecarService.disable(namespace, contextId, sidecarType);
        // Switch to chat if we disabled the active tab
        if (activeTab === `sidecar-${sidecarType}`) {
          setActiveTab('chat');
        }
      }
      // Refresh list
      const list = await sidecarService.list(namespace, contextId);
      setSidecars(list);
    } catch (e) {
      console.error('Sidecar toggle error:', e);
    }
  };

  const handleSidecarToggleAutoApprove = async (sidecarType: string, auto: boolean) => {
    if (!contextId || !namespace) return;
    try {
      await sidecarService.updateConfig(namespace, contextId, sidecarType, { auto_approve: auto });
      const list = await sidecarService.list(namespace, contextId);
      setSidecars(list);
    } catch (e) {
      console.error('Sidecar auto-approve toggle error:', e);
    }
  };

  const handleSidecarConfigChange = async (sidecarType: string, key: string, value: unknown) => {
    if (!contextId || !namespace) return;
    try {
      await sidecarService.updateConfig(namespace, contextId, sidecarType, { [key]: value });
      const list = await sidecarService.list(namespace, contextId);
      setSidecars(list);
    } catch (e) {
      console.error('Sidecar config change error:', e);
    }
  };

  const handleSidecarReset = async (sidecarType: string) => {
    if (!contextId || !namespace) return;
    try {
      await sidecarService.reset(namespace, contextId, sidecarType);
      const list = await sidecarService.list(namespace, contextId);
      setSidecars(list);
    } catch (e) {
      console.error('Sidecar reset error:', e);
    }
  };

  // SandboxConfig disabled — model/repo/branch not yet wired to backend
  // const [config, setConfig] = useState({ model: 'gpt-4o-mini', repo: '', branch: 'main' });

  // Fetch agent card to get skills for / autocomplete
  const { data: agentCard } = useQuery({
    queryKey: ['sandbox-agent-card', namespace, selectedAgent],
    queryFn: () => sandboxService.getAgentCard(namespace, selectedAgent),
    enabled: !!namespace && !!selectedAgent,
    staleTime: 60000,
    retry: 1,
  });

  // Built-in sandbox tools — always available for / autocomplete
  const BUILTIN_TOOLS = [
    { id: 'shell', name: 'Shell', description: 'Execute a shell command in the sandbox' },
    { id: 'file_read', name: 'File Read', description: 'Read a file from the workspace' },
    { id: 'file_write', name: 'File Write', description: 'Write content to a file' },
    { id: 'web_fetch', name: 'Web Fetch', description: 'Fetch content from a URL' },
    { id: 'explore', name: 'Explore', description: 'Spawn a read-only sub-agent for research' },
    { id: 'delegate', name: 'Delegate', description: 'Spawn a child agent session for a task' },
  ];
  // Merge agent card skills (e.g., loaded from .claude/skills/) with built-in tools.
  // Agent card skills come first, then built-in tools that aren't already listed.
  const cardSkills = agentCard?.skills || [];
  const cardIds = new Set(cardSkills.map((s: { id: string }) => s.id));
  const agentSkills = [
    ...cardSkills.filter((s: { id: string }) => !BUILTIN_TOOLS.some((t) => t.id === s.id)),
    ...BUILTIN_TOOLS.filter((t) => !cardIds.has(t.id)),
  ];

  // Reset whisperer dismiss state when input changes
  useEffect(() => {
    setSkillWhispererDismissed(false);
  }, [input]);

  // Handle skill selection from whisperer
  const handleSkillSelect = useCallback((skillId: string) => {
    // Replace the /query part with the selected skill
    setInput((prev) => prev.replace(/(?:^|\s)\/([\w:.-]*)$/, (match) => {
      const prefix = match.startsWith(' ') ? ' ' : '';
      return `${prefix}/${skillId} `;
    }));
    setSkillWhispererDismissed(false);
  }, []);

  /** Handle HITL approve action. */
  const handleHitlApprove = useCallback(async () => {
    if (!namespace || !contextId) return;
    try {
      await sandboxService.approveSession(namespace, contextId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to approve';
      setError(msg);
    }
  }, [namespace, contextId]);

  /** Handle HITL deny action. */
  const handleHitlDeny = useCallback(async () => {
    if (!namespace || !contextId) return;
    try {
      await sandboxService.denySession(namespace, contextId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to deny';
      setError(msg);
    }
  }, [namespace, contextId]);

  /** Convert a history message from the API into a Message for display. */
  const toMessage = (
    h: { role: string; parts?: Array<Record<string, unknown>>; _index?: number; username?: string; metadata?: Record<string, unknown> },
    i: number
  ): Message => {
    const firstPart = h.parts?.[0] as Record<string, unknown> | undefined;

    // Stable sort key: prefer backend _index, fall back to array position
    const order = h._index ?? i;

    // Only treat as tool data if it's an explicit tool call/result/thinking event
    const toolTypes = ['tool_call', 'tool_result', 'thinking', 'hitl_request', 'hitl_response', 'graph_event'];
    if (firstPart?.kind === 'data' && toolTypes.includes(firstPart?.type as string)) {
      return {
        id: `history-${order}`,
        role: h.role as 'user' | 'assistant',
        content: '',
        timestamp: new Date(),
        toolData: firstPart as unknown as ToolCallData,
        order,
      };
    }

    // Extract text from all parts (handles kind: "text", kind: "data" with text, etc.)
    const content = h.parts
      ?.map((p) => {
        if (typeof p.text === 'string') return p.text;
        // Data parts that aren't tool calls may contain text content
        if (p.kind === 'data' && typeof p.content === 'string') return p.content;
        return '';
      })
      .filter(Boolean)
      .join('') || '';

    return {
      id: `history-${order}`,
      role: h.role as 'user' | 'assistant',
      content,
      timestamp: new Date(),
      username: h.username || (h.metadata?.username as string | undefined),
      order,
    };
  };

  /** Subscribe to a running session's event stream via tasks/resubscribe. */
  const _subscribeToSession = async (ns: string, ctxId: string) => {
    // Cancel any existing subscribe stream before starting a new one
    if (subscribeAbortRef.current) {
      subscribeAbortRef.current.abort();
      subscribeAbortRef.current = null;
    }
    const controller = new AbortController();
    subscribeAbortRef.current = controller;

    try {
      const token = await getToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const url = `/api/v1/sandbox/${encodeURIComponent(ns)}/sessions/${encodeURIComponent(ctxId)}/subscribe`;
      const response = await fetch(url, { headers, signal: controller.signal });
      if (!response.ok || !response.body) {
        console.log('[subscribe] Not available or session completed');
        return;
      }

      console.log('[subscribe] Connected to live stream, status:', response.status, 'content-type:', response.headers.get('content-type'));
      setIsStreaming(true);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            try {
              const data = JSON.parse(raw);
              console.log('[subscribe] Raw data:', JSON.stringify(data).substring(0, 200));
              if (data.done) {
                console.log('[subscribe] Stream done — finalizing loops');
                // Mark loops as done (if reporter ran) or failed (if no final answer)
                setAgentLoops((prev) => {
                  const next = new Map(prev);
                  for (const [id, loop] of next) {
                    if (loop.status === 'done') continue;
                    if (loop.finalAnswer) {
                      next.set(id, { ...loop, status: 'done' });
                    } else {
                      next.set(id, { ...loop, status: 'failed', failureReason: loop.failureReason || 'Agent stopped without producing a final answer.' });
                    }
                  }
                  return next;
                });
                return;
              }
              if (data.ping) { console.log('[subscribe] ping'); continue; }
              if (data.loop_id && data.loop_event) {
                const evt = data.loop_event as LoopEvent;
                evt.loop_id = evt.loop_id || data.loop_id;
                console.log('[subscribe] Event:', evt.type, 'step:', evt.step, 'loop:', evt.loop_id);
                // Apply loop event using the canonical reducer
                setAgentLoops((prev) => {
                  const next = new Map(prev);
                  const loopId = evt.loop_id;
                  let existing = next.get(loopId);
                  if (!existing) {
                    existing = createDefaultAgentLoop(loopId);
                    existing.userMessage = lastUserMessageRef.current || undefined;
                  }
                  next.set(loopId, applyLoopEvent(existing, evt));
                  return next;
                });
              }
            } catch {
              // skip parse errors
            }
          }
        }
      } finally {
        reader.releaseLock();
        setIsStreaming(false);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        console.log('[subscribe] Aborted (session changed)');
      } else {
        console.warn('[subscribe] Error:', err);
      }
      setIsStreaming(false);
    } finally {
      if (subscribeAbortRef.current === controller) {
        subscribeAbortRef.current = null;
      }
    }
  };

  /** Load the initial (most recent) page of history.
   *
   * Uses parallel fetches and batched state updates to minimize re-renders.
   * Computes all derived state (messages, loops, agent) BEFORE any setState.
   */
  const loadInitialHistory = useCallback(
    async (ns: string, ctxId: string) => {
      if (!ns || !ctxId) return;
      // Cancel any existing subscribe stream when loading new session
      if (subscribeAbortRef.current) {
        subscribeAbortRef.current.abort();
        subscribeAbortRef.current = null;
      }
      setLoadingHistory(true);

      try {
        // Parallel fetch: session metadata + history in one round-trip
        const [sessionDetail, historyPage] = await Promise.all([
          sandboxService.getSession(ns, ctxId).catch(() => null),
          sandboxService.getHistory(ns, ctxId, { limit: INITIAL_HISTORY_LIMIT }).catch(() => null),
        ]);

        // --- Compute all derived state BEFORE any setState calls ---

        // 1. Agent name
        const metaAgent = (sessionDetail?.metadata as Record<string, unknown> | null)?.agent_name as string | undefined;
        const resolvedAgent = metaAgent
          || localStorage.getItem(STORAGE_KEY_AGENT_PREFIX + ctxId)
          || new URLSearchParams(window.location.search).get('agent')
          || selectedAgentRef.current
          || 'sandbox-legion';
        if (metaAgent) {
          localStorage.setItem(STORAGE_KEY_AGENT_PREFIX + ctxId, metaAgent);
        }

        // 2. Messages and loops
        let finalMessages: Message[] = [];
        let finalLoops = new Map<string, AgentLoop>();
        let hasMore = false;
        let oldest: number | null = null;
        let shouldSubscribe = false;

        if (historyPage) {
          console.log(`[history] Loaded: ${historyPage.messages.length} messages, loop_events=${historyPage.loop_events?.length ?? 'none'}, total=${historyPage.total}`);
          const allMessages = historyPage.messages.map(toMessage);
          hasMore = historyPage.has_more;
          if (historyPage.messages.length > 0) {
            oldest = historyPage.messages[0]._index ?? 0;
            // Set the order counter above the highest backend _index so live
            // messages always sort after history messages.
            const maxIndex = Math.max(...historyPage.messages.map((m) => m._index ?? 0));
            orderCounterRef.current = maxIndex + 1_000;
          }

          // Build loops from events
          if (historyPage.loop_events) {
            const events = historyPage.loop_events as unknown as LoopEvent[];
            if (events.length > 0) {
              finalLoops = buildAgentLoops(events);
              // Keep only user messages when we have loop cards
              finalMessages = allMessages.filter((m) => m.role === 'user');
              console.log(`[history] Reconstructed ${finalLoops.size} loop(s), ${events.length} events`);

              const loopStatuses = Array.from(finalLoops.values()).map((l) => ({ id: l.id, status: l.status, hasFinalAnswer: !!l.finalAnswer, steps: l.steps.length }));
              console.log('[history] Loop statuses:', JSON.stringify(loopStatuses));
              const hasComplete = Array.from(finalLoops.values()).some((l) => l.finalAnswer);
              shouldSubscribe = !hasComplete;
              console.log('[history] hasComplete:', hasComplete, 'shouldSubscribe:', shouldSubscribe);
            } else {
              finalMessages = allMessages;
            }
          } else {
            finalMessages = allMessages;
          }
        } else if (sessionDetail?.history) {
          // Fallback: no history endpoint — use session detail
          const filtered = sessionDetail.history.filter((h: { role: string; parts?: Array<{ text?: string }> }) => {
            if (h.role === 'user') return true;
            const text = h.parts?.map((p: { text?: string }) => p.text).filter(Boolean).join('') || '';
            return text ? !isGraphDump(text) : false;
          });
          finalMessages = filtered.slice(-INITIAL_HISTORY_LIMIT).map(toMessage);
          hasMore = filtered.length > INITIAL_HISTORY_LIMIT;
        }

        // --- ONE batch of setState calls (React 18 auto-batches) ---
        setSelectedAgent(resolvedAgent);
        setMessages(finalMessages);
        setAgentLoops(finalLoops);
        setHasMoreHistory(hasMore);
        setOldestIndex(oldest);
        setLoadingHistory(false);
        setLoadingSession(false);

        // Subscribe AFTER state is settled (next tick)
        if (shouldSubscribe) {
          console.log('[history] No final answer — subscribing to live stream');
          _subscribeToSession(ns, ctxId);
        }
      } catch {
        setLoadingHistory(false);
        setLoadingSession(false);
      }
    },
    []
  );

  // Track whether we just finished streaming — skip history reload
  // because the streaming-built agentLoops are fresher than the DB.
  const justFinishedStreamingRef = useRef(false);

  // Load history on session change + sync URL if restored from localStorage
  // Skip during streaming AND skip the first !isStreaming after streaming ends.
  useEffect(() => {
    if (contextId && namespace && !isStreaming) {
      if (justFinishedStreamingRef.current) {
        // Just finished streaming — skip reload, keep streaming data
        justFinishedStreamingRef.current = false;
      } else {
        loadInitialHistory(namespace, contextId);
      }
      // Sync URL if session was restored from localStorage
      if (!searchParams.get('session') && contextId) {
        setSearchParams({ session: contextId }, { replace: true });
      }
    }
    if (isStreaming) {
      justFinishedStreamingRef.current = true;
    }
  }, [contextId, namespace, isStreaming, loadInitialHistory, searchParams, setSearchParams]);

  // ---------------------------------------------------------------------------
  // Poll for new messages when session is idle (not streaming).
  // This enables multi-tab / multi-user updates without WebSocket.
  // Stops polling when the backend reports a terminal task_state.
  // ---------------------------------------------------------------------------
  const lastUpdatedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!contextId || !namespace || isStreaming || loadingSession) return;

    // Don't poll if all loops are complete (no new events expected)
    const allLoopsDone = agentLoops.size > 0 && Array.from(agentLoops.values()).every(
      (l) => l.status === 'done' || l.status === 'failed'
    );
    if (allLoopsDone) return;

    const TERMINAL_STATES = new Set(['completed', 'failed', 'canceled', 'rejected']);

    const pollInterval = setInterval(async () => {
      try {
        // Skip events on lightweight polls — only check task_state + new messages.
        // Full event fetch happens on initial load; polling just watches for completion.
        const histPage = await sandboxService.getHistory(namespace, contextId, {
          limit: 5,
          skip_events: true,
        });

        // Backend reports terminal state — stop polling and finalize loops
        if (histPage.task_state && TERMINAL_STATES.has(histPage.task_state)) {
          console.log('[poll] Task reached terminal state:', histPage.task_state, '— stopping poll');
          clearInterval(pollInterval);

          // Mark executing loops as done/failed based on task_state
          setAgentLoops((prev) => {
            const next = new Map(prev);
            for (const [id, loop] of next) {
              if (loop.status === 'done' || loop.status === 'failed') continue;
              if (histPage.task_state === 'completed') {
                next.set(id, { ...loop, status: loop.finalAnswer ? 'done' : 'failed',
                  failureReason: loop.finalAnswer ? undefined : 'Agent completed without a final answer.' });
              } else {
                next.set(id, { ...loop, status: 'failed',
                  failureReason: `Session ${histPage.task_state}.` });
              }
            }
            return next;
          });
          return;
        }

        // Track last_updated to avoid re-processing unchanged state
        if (histPage.last_updated && histPage.last_updated === lastUpdatedRef.current) {
          return; // No changes since last poll
        }
        lastUpdatedRef.current = histPage.last_updated || null;

        if (histPage.messages.length === 0) return;

        setMessages((prev) => {
          // Dedup by _index (history-loaded messages)
          const existingIndices = new Set(
            prev
              .map((m) => {
                const match = m.id.match(/^history-(\d+)$/);
                return match ? Number(match[1]) : null;
              })
              .filter((idx): idx is number => idx !== null)
          );
          // Also dedup by content prefix (catches SSE-added messages without _index)
          const existingContent = new Set(
            prev.filter((m) => m.content?.trim()).map((m) => m.content.trim().slice(0, 100))
          );

          const newMsgs = histPage.messages
            .filter((h) => {
              if (h._index !== undefined && existingIndices.has(h._index)) return false;
              // Content-based dedup for SSE-added messages
              const text = (h.parts || [])
                .map((p: Record<string, unknown>) => (typeof p.text === 'string' ? p.text : ''))
                .filter(Boolean)
                .join('');
              if (text && existingContent.has(text.trim().slice(0, 100))) return false;
              return true;
            })
            .map(toMessage);

          if (newMsgs.length === 0) return prev;
          shouldAutoScroll.current = true;
          return [...prev, ...newMsgs];
        });
      } catch {
        // Polling failures are non-critical
      }
    }, 5000);

    return () => clearInterval(pollInterval);
  }, [contextId, namespace, isStreaming]);

  /** Load an older page of history (triggered by scrolling to top). */
  const loadOlderHistory = useCallback(async () => {
    if (!hasMoreHistory || loadingHistory || oldestIndex === null) return;
    setLoadingHistory(true);
    const container = scrollContainerRef.current;
    const prevScrollHeight = container?.scrollHeight ?? 0;

    try {
      const page = await sandboxService.getHistory(namespace, contextId, {
        limit: INITIAL_HISTORY_LIMIT,
        before: oldestIndex,
      });
      if (page.messages.length > 0) {
        setMessages((prev) => [
          ...page.messages.map(toMessage),
          ...prev,
        ]);
        setOldestIndex(page.messages[0]._index ?? 0);
        setHasMoreHistory(page.has_more);

        // Preserve scroll position after prepending
        requestAnimationFrame(() => {
          if (container) {
            const newScrollHeight = container.scrollHeight;
            container.scrollTop += newScrollHeight - prevScrollHeight;
          }
        });
      } else {
        setHasMoreHistory(false);
      }
    } catch {
      // ignore
    } finally {
      setLoadingHistory(false);
    }
  }, [hasMoreHistory, loadingHistory, oldestIndex, namespace, contextId]);

  // IntersectionObserver for infinite scroll — triggers when sentinel at top is visible
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMoreHistory && !loadingHistory) {
          loadOlderHistory();
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMoreHistory, loadingHistory, loadOlderHistory]);

  // Auto-scroll to bottom on new messages
  const shouldAutoScroll = useRef(true);
  useEffect(() => {
    if (shouldAutoScroll.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingContent]);

  const handleSelectSession = useCallback(
    (id: string, sessionAgentName?: string) => {
      const sameSession = id === contextId;
      setContextId(id);
      // Only update selectedAgent when sessionAgentName is a non-empty string.
      // When metadata is missing (race condition), preserve the current agent
      // so subsequent messages don't get routed to the wrong agent.
      if (sessionAgentName) {
        setSelectedAgent(sessionAgentName);
        if (id) localStorage.setItem(STORAGE_KEY_AGENT_PREFIX + id, sessionAgentName);
      }
      setLoadingSession(true);
      setInput('');
      setStreamingContent('');
      setIsStreaming(false);
      setError(null);
      setHasMoreHistory(false);
      setOldestIndex(null);
      shouldAutoScroll.current = true;
      if (id) {
        // Resolve the agent for the URL: prefer session agent, then localStorage, then current
        const agentForUrl = sessionAgentName
          || localStorage.getItem(STORAGE_KEY_AGENT_PREFIX + id)
          || selectedAgent;
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set('session', id);
          next.set('agent', agentForUrl);
          return next;
        });
        localStorage.setItem(STORAGE_KEY_SESSION, id);
      } else {
        setSearchParams({});
        localStorage.removeItem(STORAGE_KEY_SESSION);
      }
      // When re-selecting the same session, the useEffect keyed on contextId
      // won't fire because the value hasn't changed. Reload history explicitly.
      if (sameSession && id && namespace) {
        loadInitialHistory(namespace, id);
      }
    },
    [setSearchParams, selectedAgent, contextId, namespace, loadInitialHistory]
  );

  /** Start a new session with the chosen agent (from the New Session modal). */
  const handleNewSession = useCallback(
    (agentName: string) => {
      selectedAgentRef.current = agentName; // sync ref immediately
      setSelectedAgent(agentName);
      // Clear contextId to start fresh (no existing session)
      setContextId('');
      setMessages([]);
      setAgentLoops(new Map());
      setLoadingSession(false);
      setInput('');
      setStreamingContent('');
      setIsStreaming(false);
      setError(null);
      setHasMoreHistory(false);
      setOldestIndex(null);
      shouldAutoScroll.current = true;
      setSearchParams({});
      localStorage.removeItem(STORAGE_KEY_SESSION);
    },
    [setSearchParams]
  );

  // Persist namespace to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_NAMESPACE, namespace);
  }, [namespace]);

  /** Send via non-streaming /chat endpoint (fallback). */
  const sendNonStreaming = async (
    messageToSend: string,
    headers: Record<string, string>,
    skill?: string,
  ) => {
    const body: Record<string, unknown> = {
      message: messageToSend,
      session_id: contextIdRef.current || undefined,
      agent_name: selectedAgentRef.current || 'sandbox-legion',
    };
    if (skill) body.skill = skill;
    const response = await fetch(
      `/api/v1/sandbox/${encodeURIComponent(namespace)}/chat`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      }
    );

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP error: ${response.status}`);
    }

    const data = await response.json();

    if (data.context_id && !contextId) {
      setContextId(data.context_id);
      setSearchParams({ session: data.context_id });
      localStorage.setItem(STORAGE_KEY_SESSION, data.context_id);
    }

    if (data.content) {
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: data.content,
          timestamp: new Date(),
          order: orderCounterRef.current++,
        },
      ]);
    }
  };

  /** Update or create an AgentLoop in the loops map. */
  const updateLoop = useCallback((loopId: string, updater: (prev: AgentLoop) => AgentLoop) => {
    setAgentLoops((prev) => {
      const next = new Map(prev);
      const existing = next.get(loopId) || createDefaultAgentLoop(loopId);
      next.set(loopId, updater(existing));
      return next;
    });
  }, []);

  /** Attempt SSE streaming via /chat/stream, return true on success. */
  const sendStreaming = async (
    messageToSend: string,
    headers: Record<string, string>,
    skill?: string,
  ): Promise<boolean> => {
    const streamUrl = sandboxService.getStreamUrl(namespace);
    const agentForRequest = selectedAgentRef.current || 'sandbox-legion';
    const body: Record<string, unknown> = {
      message: messageToSend,
      session_id: contextIdRef.current || undefined,
      agent_name: agentForRequest,
    };
    if (skill) body.skill = skill;
    if (sessionModelOverride) body.model = sessionModelOverride;
    const response = await fetch(streamUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      // If streaming not supported (404) or server error, signal fallback
      return false;
    }

    const reader = response.body?.getReader();
    if (!reader) return false;

    const decoder = new TextDecoder();
    let accumulatedContent = '';
    let buffer = '';
    let seenLoopId = false; // Once any loop_id event seen, suppress flat messages
    let msgCountBeforeStream = 0; // Track count to only remove current-turn flat messages
    const collectedMessages: Message[] = [];

    // Snapshot current message count so retroactive cleanup only
    // removes flat messages from THIS turn, not previous turns
    setMessages((prev) => { msgCountBeforeStream = prev.length; return prev; });

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;

          try {
            const data = JSON.parse(line.slice(6));

            // Track session from the streaming response
            if (data.session_id && !contextId) {
              setContextId(data.session_id);
              // Only add session param — preserve existing agent param from URL
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('session', data.session_id);
                return next;
              });
              localStorage.setItem(STORAGE_KEY_SESSION, data.session_id);
              const currentAgent = new URLSearchParams(window.location.search).get('agent') || agentForRequest;
              localStorage.setItem(STORAGE_KEY_AGENT_PREFIX + data.session_id, currentAgent);
            }

            // Handle agent loop events (grouped by loop_id)
            // The backend forwards loop events with loop_id at top level
            // and the full event in data.loop_event
            if (data.loop_id) {
              if (!seenLoopId) {
                // First loop event: retroactively remove flat messages
                // from THIS turn only (keep previous turns intact)
                seenLoopId = true;
                // Clear any pre-loop flat content to prevent duplicates
                accumulatedContent = '';
                setStreamingContent('');
                setMessages((prev) => [
                  ...prev.slice(0, msgCountBeforeStream),
                  ...prev.slice(msgCountBeforeStream).filter((m) => m.role === 'user'),
                ]);
              }
              const loopId = data.loop_id;
              const le = data.loop_event || data;
              const eventType = le.type;
              console.log(`[sse] LOOP_RECV loop=${loopId?.substring(0, 8)} type=${eventType} step=${le.step ?? ''} tools=${le.tools?.length ?? 0}`);

              // Apply event using shared builder
              updateLoop(loopId, (prev) => applyLoopEvent(prev, le));

              // Don't process loop events through the old flat pipeline
              continue;
            }

            // Handle HITL (Human-in-the-Loop) events
            if (data.event?.type === 'hitl_request') {
              collectedMessages.push({
                id: `hitl-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                role: 'assistant',
                content: '',
                timestamp: new Date(),
                order: orderCounterRef.current++,
                toolData: {
                  type: 'hitl_request',
                  command: data.event.taskId || '',
                  reason: data.event.message || 'Agent requests approval',
                },
              });
              // Show the HITL message immediately (snapshot for StrictMode safety)
              const hitlSnapshot = collectedMessages.splice(0);
              setMessages((prev) => [...prev, ...hitlSnapshot]);
              setStreamingContent('');
            }

            // Handle delegation events (Session E: sub-agent spawning)
            if (data.event && DELEGATION_EVENT_TYPES.includes(data.event.type)) {
              collectedMessages.push({
                id: `deleg-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                role: 'assistant',
                content: '',
                timestamp: new Date(),
                order: orderCounterRef.current++,
                toolData: {
                  type: data.event.type,
                  child_context_id: data.event.child_context_id,
                  delegation_mode: data.event.delegation_mode,
                  task: data.event.task,
                  variant: data.event.variant,
                  state: data.event.state,
                  content: data.content,
                  message: data.event.message,
                },
              });
              // Flush delegation events immediately (snapshot for StrictMode safety)
              const delegSnapshot = collectedMessages.splice(0);
              setMessages((prev) => [...prev, ...delegSnapshot]);
            }

            // Parse and immediately flush tool call/result events
            // Skip if in loop mode — AgentLoopCard handles all rendering
            if (!seenLoopId && data.event && data.event.message) {
              const eventText = data.event.message;
              let hadToolEvents = false;
              for (const eventLine of eventText.split('\n')) {
                const parsed = parseGraphEvent(eventLine);
                if (parsed && (parsed.type === 'tool_call' || parsed.type === 'tool_result' || parsed.type === 'llm_response')) {
                  collectedMessages.push({
                    id: `stream-event-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                    role: 'assistant',
                    content: '',
                    timestamp: new Date(),
                    order: orderCounterRef.current++,
                    toolData: parsed,
                  });
                  hadToolEvents = true;
                }
              }
              if (hadToolEvents) {
                const snapshot = collectedMessages.splice(0);
                setMessages((prev) => [...prev, ...snapshot]);
              }
            }

            // Accumulate content for real-time display (final answer)
            if (data.content) {
              if (!seenLoopId) {
                // No loop active — normal flat content display
                accumulatedContent += data.content;
                setStreamingContent(accumulatedContent);
              } else {
                // Loop mode: flat content is the final answer.
                // Use it to fill the loop's finalAnswer (prevents "stuck in reasoning").
                accumulatedContent += data.content;
                setAgentLoops((prev) => {
                  const next = new Map(prev);
                  // Find the last active loop to attach the answer to
                  let found = false;
                  for (const [lid, loop] of [...next].reverse()) {
                    if (!loop.finalAnswer) {
                      next.set(lid, { ...loop, status: 'done', finalAnswer: accumulatedContent });
                      found = true;
                      break;
                    }
                  }
                  // Only return new map if we actually updated a loop;
                  // returning prev avoids phantom re-renders when all
                  // loops already have a finalAnswer.
                  return found ? next : prev;
                });
              }
            }

            // Handle errors from the backend
            if (data.error) {
              accumulatedContent = `Error: ${data.error}`;
              setStreamingContent(accumulatedContent);
            }

            if (data.done) {
              break;
            }
          } catch {
            // Incomplete JSON chunk -- skip
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    // Finalize: add any remaining tool call messages, then the final response.
    // In loop mode, skip flat finalization — AgentLoopCard has the content.
    if (!seenLoopId) {
      const finalSnapshot = collectedMessages.splice(0);
      if (finalSnapshot.length > 0 || accumulatedContent) {
        setMessages((prev) => [
          ...prev,
          ...finalSnapshot,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: accumulatedContent,
            timestamp: new Date(),
            order: orderCounterRef.current++,
          },
        ]);
      }
    }

    return true;
  };

  /** Cancel the in-progress agent loop: kill backend task, abort SSE stream, reset UI state. */
  const cancelCurrentLoop = async () => {
    // 1. Kill the backend task so the agent stops processing
    if (contextId) {
      try {
        await sandboxService.killSession(namespace, contextId);
      } catch (err) {
        console.warn('[cancel] Failed to kill session:', err);
      }
    }

    // 2. Abort the active subscribe/streaming SSE connection
    if (subscribeAbortRef.current) {
      subscribeAbortRef.current.abort();
      subscribeAbortRef.current = null;
    }

    // 3. Mark active agent loops as 'canceled'
    setAgentLoops((prev) => {
      const next = new Map(prev);
      for (const [id, loop] of next) {
        if (loop.status !== 'done') {
          next.set(id, { ...loop, status: 'canceled' });
        }
      }
      return next;
    });

    // 4. Reset streaming UI state
    setIsStreaming(false);
    setStreamingContent('');
    sendingRef.current = false;
  };

  const handleSendMessage = async () => {
    if (!input.trim() || sendingRef.current) return;

    // If agent is still processing, cancel the previous loop first
    if (isStreaming) {
      await cancelCurrentLoop();
    }

    sendingRef.current = true;
    // Capture and clear input immediately to prevent double-send
    const trimmed = input.trim();
    setInput('');

    shouldAutoScroll.current = true;

    // Parse /skill:name prefix from message (e.g. "/rca:ci #758" → skill="rca:ci", text="#758")
    const skillMatch = trimmed.match(/^\/([\w:.-]+)\s*(.*)/s);
    const skill = skillMatch ? skillMatch[1] : undefined;

    lastUserMessageRef.current = trimmed;
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
      order: orderCounterRef.current++,
      username: currentUsername,
    };
    setMessages((prev) => [...prev, userMessage]);
    // Send full text to backend (preserve skill prefix in history)
    const messageToSend = trimmed;
    setIsStreaming(true);
    setStreamingContent('');
    setError(null);

    try {
      const token = await getToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      // Try streaming first; fall back to non-streaming ONLY if the
      // initial connection failed (HTTP error). Once the stream connects
      // and starts receiving data, the message has already been sent to
      // the agent — do NOT resend via non-streaming fallback.
      let streamed = false;
      try {
        streamed = await sendStreaming(messageToSend, headers, skill);
      } catch (streamErr) {
        // Streaming threw — but if we got a 200 response, the message
        // was already sent. Only fall back on connection/pre-send errors.
        const streamMsg = streamErr instanceof Error ? streamErr.message : '';
        if (streamMsg.includes('connection') || streamMsg.includes('chunked') || streamMsg.includes('network')) {
          throw streamErr; // Let the outer catch handle with backoff
        }
        // Stream reader error after 200 — message was sent, don't resend
        console.warn('[chat] Stream reader error (message already sent):', streamMsg);
        streamed = true;
      }

      if (!streamed) {
        await sendNonStreaming(messageToSend, headers, skill);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to send';
      const isConnectionError = msg.includes('connection') || msg.includes('chunked') || msg.includes('network');
      if (isConnectionError && contextId) {
        // Connection dropped — agent may still be processing.
        // Backoff loop: poll session status until completed or timeout.
        setError('Connection interrupted — waiting for agent to finish...');
        const pollSession = async (attempt: number) => {
          if (attempt > 5) {
            setError('Agent did not complete — try refreshing the page.');
            return;
          }
          const delay = Math.min(2000 * Math.pow(1.5, attempt), 10000);
          await new Promise((r) => setTimeout(r, delay));
          try {
            const detail = await sandboxService.getSession(namespace, contextId);
            const state = detail?.status?.state;
            if (state === 'completed' || state === 'failed') {
              await loadInitialHistory(namespace, contextId);
              setError(null);
            } else {
              setError(`Agent still working (attempt ${attempt + 1}/5)...`);
              await pollSession(attempt + 1);
            }
          } catch {
            await pollSession(attempt + 1);
          }
        };
        pollSession(0);
      } else {
        setError(msg);
        setMessages((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: 'assistant',
            content: `Error: ${msg}`,
            timestamp: new Date(),
            order: orderCounterRef.current++,
          },
        ]);
      }
    } finally {
      sendingRef.current = false;
      setIsStreaming(false);
      setStreamingContent('');
      // Mark active agent loops based on completion state.
      // If the loop has a finalAnswer (reporter ran), mark as "done".
      // Otherwise the stream was interrupted — mark as "failed" with reason.
      setAgentLoops((prev) => {
        const next = new Map(prev);
        for (const [id, loop] of next) {
          if (loop.status === 'done') continue;
          if (loop.finalAnswer) {
            next.set(id, { ...loop, status: 'done' });
          } else {
            // Don't mark as "failed" — the agent may still be processing.
            // Keep as "executing" so the UI shows an in-progress state.
            // The user can reload to check for updates.
            next.set(id, {
              ...loop,
              status: 'executing',
            });
          }
        }
        return next;
      });
    }
  };

  return (
    <PageSection variant="light" padding={{ default: 'noPadding' }}>
      <div style={{ display: 'flex', height: 'calc(100vh - 80px)' }}>
        {/* Left column: sessions + sandbox agents — sticky, doesn't scroll with main */}
        <div
          style={{
            width: 280,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            position: 'sticky',
            top: 0,
            borderRight: '1px solid var(--pf-v5-global--BorderColor--100)',
            overflowY: 'auto',
          }}
        >
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <SessionSidebar
              namespace={namespace}
              activeContextId={contextId}
              onSelectSession={handleSelectSession}
              onNewSession={handleNewSession}
              selectedAgentName={selectedAgent}
            />
          </div>
        </div>

        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            padding: 16,
            overflow: 'hidden',
            minWidth: 0,
          }}
        >
          {/* Header info bar */}
          <Split hasGutter style={{ marginBottom: 8, alignItems: 'center' }}>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Agent:</span>
              <Tooltip content="Active sandbox agent handling this session">
                <Label isCompact color="purple">{selectedAgent}</Label>
              </Tooltip>
              <Tooltip content="Reconfigure agent">
                <Button
                  variant="plain"
                  size="sm"
                  style={{ padding: '0 4px', marginLeft: 4 }}
                  onClick={() => setReconfigureOpen(true)}
                >
                  <CogIcon />
                </Button>
              </Tooltip>
            </SplitItem>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Namespace:</span>
              <Tooltip content="Kubernetes namespace where the agent runs">
                <Label isCompact color="blue">{namespace}</Label>
              </Tooltip>
            </SplitItem>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Model:</span>
              <ModelSwitcher
                currentModel={sessionModelOverride || (agentCard as Record<string, unknown>)?.model as string || 'llama4-scout'}
                onModelChange={setSessionModelOverride}
                namespace={namespace}
              />
            </SplitItem>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Security:</span>
              <Tooltip content={
                <div>
                  <div><strong>Active Security Features:</strong></div>
                  <div>&#10003; SPIFFE workload identity</div>
                  <div>&#10003; Istio mTLS (ambient mode)</div>
                  <div>&#10003; Permission-checked shell execution</div>
                  <div>&#10003; Path-traversal prevention</div>
                  <div>&#10003; TOFU config integrity verification</div>
                  <div>&#10003; Per-session workspace isolation</div>
                </div>
              }>
                <Label isCompact color="green" icon={<ShieldAltIcon />}>
                  Secured
                </Label>
              </Tooltip>
            </SplitItem>
            {contextId && (
              <SplitItem>
                <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Session:</span>
                <Tooltip content={contextId}>
                  <Label isCompact color="grey">{contextId.slice(0, 8)}...</Label>
                </Tooltip>
              </SplitItem>
            )}
            <SplitItem isFilled />
          </Split>

          {/* SandboxConfig disabled — model/repo/branch not yet wired to backend.
              TODO: wire config to agent via A2A message metadata or per-session config endpoint.
          <SandboxConfig config={config} onChange={setConfig} />
          */}

          {error && (
            <Alert
              variant="danger"
              title={error}
              isInline
              style={{ marginBottom: 8 }}
            />
          )}

          {/* Tab bar — stays pinned */}
          <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid var(--pf-v5-global--BorderColor--100)', flexShrink: 0, marginBottom: 8 }}>
            {['chat', 'stats', 'llm-usage', 'sub-sessions', 'files', 'pod'].map((tab) => (
              <button
                key={tab}
                role="tab"
                onClick={() => {
                  setActiveTab(tab);
                  setSearchParams(prev => {
                    const next = new URLSearchParams(prev);
                    next.set('tab', tab);
                    return next;
                  }, { replace: true });
                }}
                style={{
                  padding: '8px 16px',
                  border: 'none',
                  borderBottom: activeTab === tab ? '3px solid var(--pf-v5-global--primary-color--100)' : '3px solid transparent',
                  backgroundColor: 'transparent',
                  fontWeight: activeTab === tab ? 600 : 400,
                  color: activeTab === tab ? 'var(--pf-v5-global--primary-color--100)' : 'inherit',
                  cursor: 'pointer',
                  fontSize: '0.95em',
                  textTransform: 'capitalize',
                }}
              >
                {tab === 'chat' ? 'Chat' : tab === 'stats' ? 'Stats' : tab === 'llm-usage' ? 'LLM Usage' : tab === 'sub-sessions' ? `Sub-sessions${childSessionCount > 0 ? ` (${childSessionCount})` : ''}` : tab === 'files' ? 'Files' : 'Pod'}
              </button>
            ))}
            {/* Sidecar tabs removed — sidecars now in right panel */}
          </div>

          {/* Tab content — fills remaining space */}
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>

          {activeTab === 'chat' && (
          <>
          {/* View mode toggle */}
          <FloatingViewBar viewMode={viewMode} onChange={handleViewModeChange} />
          {/* Chat messages */}
          <Card style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            <CardBody
              ref={scrollContainerRef}
              data-testid="chat-messages"
              style={{
                height: '100%',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                padding: '12px 16px',
              }}
            >
            {loadingSession && (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Spinner size="lg" />
              </div>
            )}
            {!loadingSession && (<>

              {/* Sentinel for infinite scroll — loads older messages */}
              <div ref={sentinelRef} style={{ minHeight: 1 }} />
              {loadingHistory && (
                <div style={{ padding: '12px 14px' }}>
                  {/* Skeleton: user message placeholder */}
                  <div style={{
                    display: 'flex', justifyContent: 'flex-end', marginBottom: 8,
                  }}>
                    <div style={{
                      height: 40, width: '60%', maxWidth: 400,
                      backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                      borderRadius: 8, opacity: 0.6,
                    }} />
                  </div>
                  {/* Skeleton: agent loop placeholder */}
                  <div style={{
                    display: 'flex', gap: 10, padding: '10px 14px', marginBottom: 4,
                    borderRadius: 8, border: '1px solid var(--pf-v5-global--BorderColor--100)',
                    backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
                    opacity: 0.6, minHeight: 80,
                  }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '50%',
                      backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                    }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ height: 14, width: '70%', backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)', borderRadius: 4, marginBottom: 8 }} />
                      <div style={{ height: 10, width: '40%', backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)', borderRadius: 4 }} />
                    </div>
                  </div>
                </div>
              )}

              {/* Welcome card — only when no messages */}
              {messages.length === 0 && !isStreaming && (
              <div
                data-testid="welcome-card"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 32,
                  flex: 1,
                }}
              >
                <div style={{ maxWidth: 480, textAlign: 'center' }}>
                  {/* Agent name */}
                  <h3 style={{ margin: '0 0 4px', fontSize: '1.1em' }}>{selectedAgent}</h3>
                  <p style={{ margin: '0 0 8px', fontSize: '0.8em', color: 'var(--pf-v5-global--Color--200)' }}>
                    {(agentCard as Record<string, unknown>)?.model as string || 'llama4-scout'} &middot; {namespace}
                  </p>

                    {/* Available tools + example prompts */}
                    {(
                      <>
                        {agentSkills.length > 0 && (
                          <div style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: '0.8em', color: 'var(--pf-v5-global--Color--200)', marginBottom: 6 }}>
                              Available tools
                            </div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'center' }}>
                              {agentSkills.slice(0, 8).map((skill: { id?: string; name?: string }) => (
                                <Label key={skill.id || skill.name} isCompact color="blue">
                                  {skill.name || skill.id}
                                </Label>
                              ))}
                              {agentSkills.length > 8 && (
                                <Label isCompact>+{agentSkills.length - 8} more</Label>
                              )}
                            </div>
                          </div>
                        )}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {[
                            'List the contents of the workspace directory',
                            'Write a Python script that prints hello world',
                            'What tools do you have available?',
                          ].map((prompt) => (
                            <button
                              key={prompt}
                              data-testid="example-prompt"
                              onClick={() => setInput(prompt)}
                              style={{
                                padding: '8px 12px',
                                borderRadius: 6,
                                border: '1px solid var(--pf-v5-global--BorderColor--100)',
                                backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                                cursor: 'pointer',
                                fontSize: '0.85em',
                                textAlign: 'left',
                                color: 'inherit',
                              }}
                            >
                              {prompt}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                </div>
              </div>
              )}

              {/* Render messages grouped into turns, with loop cards interleaved */}
              {(() => {
                const turns = groupMessagesIntoTurns(messages);
                const loopArray = Array.from(agentLoops.values());
                const hasLoopCards = loopArray.length > 0;
                const elements: React.ReactNode[] = [];

                // Render each turn, pairing with the corresponding loop card by position
                turns.forEach((turn, idx) => {
                  elements.push(
                    <React.Fragment key={turn.user?.id || `turn-${idx}`}>
                      {/* User message */}
                      {turn.user && (
                        <ChatBubble
                          msg={turn.user}
                          currentUsername={currentUsername}
                          namespace={namespace}
                          agentName={selectedAgent}
                        />
                      )}
                      {/* Agent turn — collapsed (only when no loop cards handle the content) */}
                      {turn.assistantMessages.length > 0 && !hasLoopCards && (
                        <CollapsedTurn
                          turn={turn}
                          namespace={namespace}
                          agentName={selectedAgent}
                          onApprove={
                            turn.assistantMessages.some((m) => m.toolData?.type === 'hitl_request')
                              ? handleHitlApprove
                              : undefined
                          }
                          onDeny={
                            turn.assistantMessages.some((m) => m.toolData?.type === 'hitl_request')
                              ? handleHitlDeny
                              : undefined
                          }
                        />
                      )}
                      {/* Loop card for this turn (paired by position) */}
                      {hasLoopCards && idx < loopArray.length && renderLoopCard(loopArray[idx], isStreaming && idx === loopArray.length - 1)}
                    </React.Fragment>,
                  );
                });

                // Render any remaining loop cards that exceed the number of turns
                // (e.g. during live streaming when the loop is the latest item)
                loopArray.slice(turns.length).forEach((loop) => {
                  elements.push(renderLoopCard(loop, isStreaming));
                });

                return elements;
              })()}

              {/* Streaming indicator — only when no loop cards handle progress */}
              {isStreaming && agentLoops.size === 0 && (
                <div
                  style={{
                    display: 'flex',
                    gap: 10,
                    padding: '10px 14px',
                    borderRadius: 8,
                    border:
                      '1px solid var(--pf-v5-global--BorderColor--100)',
                  }}
                >
                  <div
                    style={{
                      flexShrink: 0,
                      width: 32,
                      height: 32,
                      borderRadius: '50%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor:
                        'var(--pf-v5-global--success-color--100)',
                      color: '#fff',
                      fontSize: 14,
                    }}
                  >
                    <RobotIcon />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: '0.9em', marginBottom: 4 }}>
                      {selectedAgent || 'Agent'}{' '}
                      <Label color="blue" isCompact style={{ marginLeft: 4 }}>
                        thinking
                      </Label>
                    </div>
                    {streamingContent ? (
                      <div className="sandbox-markdown" style={{ fontSize: '0.92em' }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {streamingContent}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <Spinner size="sm" />
                    )}
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>)}
            </CardBody>
          </Card>

          {/* Input area */}
          <Split hasGutter style={{ marginTop: 8 }}>
            <SplitItem isFilled style={{ position: 'relative' }}>
              {!skillWhispererDismissed && agentSkills.length > 0 && (
                <SkillWhisperer
                  skills={agentSkills}
                  input={input}
                  onSelect={handleSkillSelect}
                  onDismiss={() => setSkillWhispererDismissed(true)}
                />
              )}
              <TextArea
                value={input}
                onChange={(_e, value) => setInput(value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder="Type your message... (Enter to send, Shift+Enter for newline)"
                aria-label="Message input"
                rows={2}
              />
            </SplitItem>
            <SplitItem>
              {isStreaming ? (
                <Button
                  variant="danger"
                  onClick={cancelCurrentLoop}
                  icon={<StopCircleIcon />}
                  data-testid="cancel-button"
                >
                  Cancel
                </Button>
              ) : (
                <Button
                  variant="primary"
                  onClick={handleSendMessage}
                  isDisabled={!input.trim()}
                  icon={<PaperPlaneIcon />}
                  data-testid="send-button"
                >
                  Send
                </Button>
              )}
            </SplitItem>
          </Split>

          </>
          )}

          {activeTab === 'stats' && (
              <SessionStatsPanel
                agentLoops={agentLoops}
                messages={messages}
                contextId={contextId}
                isVisible={activeTab === 'stats'}
              />
          )}

          {activeTab === 'llm-usage' && contextId && (
              <LlmUsagePanel
                contextId={contextId}
                isVisible={activeTab === 'llm-usage'}
              />
          )}

          {activeTab === 'sub-sessions' && contextId && (
              <SubSessionsPanel
                contextId={contextId}
                namespace={namespace}
                onNavigateToSession={(cid, agent) => {
                  handleSelectSession(cid, agent);
                  setActiveTab('chat');
                }}
              />
          )}

          {activeTab === 'files' && (
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <FileBrowser
                  namespace={namespace}
                  agentName={selectedAgent}
                  contextId={contextId || undefined}
                  embedded
                />
              </div>
          )}

          {activeTab === 'pod' && (
              <div style={{ flex: 1, overflow: 'auto' }}>
                <PodStatusPanel
                  namespace={namespace}
                  agentName={selectedAgent}
                />
              </div>
          )}

          </div> {/* end tab content */}

        </div>

        {/* Right panel: Sidecar Agents */}
        {contextId && (
          <div
            style={{
              width: 280,
              flexShrink: 0,
              borderLeft: '1px solid var(--pf-v5-global--BorderColor--100)',
              height: '100%',
              overflowY: 'auto',
            }}
          >
            <SidecarPanel
              namespace={namespace}
              contextId={contextId}
              sidecars={sidecars}
              onToggleEnable={handleSidecarToggleEnable}
              onToggleAutoApprove={handleSidecarToggleAutoApprove}
              onConfigChange={handleSidecarConfigChange}
              onReset={handleSidecarReset}
            />
          </div>
        )}
      </div>

      {/* Markdown styling */}
      <style>{`
        .sandbox-markdown pre {
          background: var(--pf-v5-global--BackgroundColor--dark-300);
          color: var(--pf-v5-global--Color--light-100);
          padding: 12px;
          border-radius: 6px;
          overflow-x: auto;
          font-size: 0.88em;
          margin: 8px 0;
        }
        .sandbox-markdown code {
          font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
          font-size: 0.9em;
        }
        .sandbox-markdown :not(pre) > code {
          background: var(--pf-v5-global--BackgroundColor--200);
          padding: 2px 5px;
          border-radius: 3px;
        }
        .sandbox-markdown table {
          border-collapse: collapse;
          margin: 8px 0;
          width: 100%;
        }
        .sandbox-markdown th,
        .sandbox-markdown td {
          border: 1px solid var(--pf-v5-global--BorderColor--100);
          padding: 6px 10px;
          text-align: left;
        }
        .sandbox-markdown th {
          background: var(--pf-v5-global--BackgroundColor--200);
          font-weight: 600;
        }
        .sandbox-markdown p {
          margin: 4px 0;
        }
        .sandbox-markdown ul,
        .sandbox-markdown ol {
          margin: 4px 0;
          padding-left: 20px;
        }
        .sandbox-markdown blockquote {
          border-left: 3px solid var(--pf-v5-global--BorderColor--100);
          padding-left: 12px;
          margin: 8px 0;
          color: var(--pf-v5-global--Color--200);
        }
      `}</style>

      {/* Reconfigure Modal */}
      <Modal
        variant={ModalVariant.large}
        title={`Reconfigure ${selectedAgent}`}
        isOpen={reconfigureOpen}
        onClose={() => setReconfigureOpen(false)}
        showClose
      >
        <SandboxWizard
          mode="reconfigure"
          agentName={selectedAgent}
          namespace={namespace}
          onClose={() => setReconfigureOpen(false)}
          onSuccess={() => setReconfigureOpen(false)}
        />
      </Modal>
    </PageSection>
  );
};
