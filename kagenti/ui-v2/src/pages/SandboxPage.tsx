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
  Tabs,
  Tab,
  TabTitleText,
} from '@patternfly/react-core';
import { PaperPlaneIcon, UserIcon, RobotIcon, CheckCircleIcon, TimesCircleIcon, FolderOpenIcon, FileIcon, CogIcon, ShieldAltIcon } from '@patternfly/react-icons';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useQuery } from '@tanstack/react-query';
import { sandboxService, chatService } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { SessionSidebar } from '../components/SessionSidebar';
import { SandboxAgentsPanel } from '../components/SandboxAgentsPanel';
import { SkillWhisperer } from '../components/SkillWhisperer';
// SandboxConfig disabled — model/repo/branch not yet wired to backend
// import { SandboxConfig, SandboxConfigValues } from '../components/SandboxConfig';
// NamespaceSelector removed from session view — namespace shown as read-only Label
// import { NamespaceSelector } from '../components/NamespaceSelector';
import { DelegationCard, type DelegationState } from '../components/DelegationCard';
import { AgentLoopCard } from '../components/AgentLoopCard';
import { FilePreviewModal } from '../components/FilePreviewModal';
import { SessionStatsPanel } from '../components/SessionStatsPanel';
import type { AgentLoop } from '../types/agentLoop';

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
}

/** Number of history messages to show initially; rest behind "Load earlier". */
const INITIAL_HISTORY_LIMIT = 30;

/** Format timestamp for display. */
function formatMsgTime(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Detect and filter out LangGraph intermediate status dumps from history. */
function isGraphDump(text: string): boolean {
  return /^(assistant|tools|__end__):\s/m.test(text.trim());
}

/**
 * Convert file paths in text to markdown links pointing to the file browser.
 * Matches absolute paths like /workspace/foo.py, /data/bar.txt, /repos/src/main.go
 */
function linkifyFilePaths(text: string, namespace: string, agentName: string): string {
  return text.replace(
    /(?<!\w)(\/(?:workspace|data|repos|app|home|tmp|opt|var|srv)\/[\w./_-]+\.\w+)/g,
    (match) => `[${match}](/sandbox/files/${namespace}/${agentName}?path=${encodeURIComponent(match)})`
  );
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
      return <a href={href}>{children}</a>;
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
  const [hitlActioned, setHitlActioned] = useState<'approved' | 'denied' | null>(null);

  if (data.type === 'tool_call') {
    return (
      <div
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
          {data.tools?.map((t) => t.name).join(', ') || 'unknown'}
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
      <div
        style={{
          margin: '4px 0',
          padding: '6px 10px',
          borderLeft: '3px solid var(--pf-v5-global--warning-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0',
          fontSize: '0.85em',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--pf-v5-global--warning-color--100)' }}>
          Approval Required
        </div>
        <pre style={{ margin: '4px 0', padding: 8, fontSize: '0.9em', overflow: 'auto' }}>
          Command: {data.command}{'\n'}Reason: {data.reason}
        </pre>
        {hitlActioned ? (
          <div style={{ marginTop: 8 }}>
            <Label
              color={hitlActioned === 'approved' ? 'green' : 'red'}
              icon={hitlActioned === 'approved' ? <CheckCircleIcon /> : <TimesCircleIcon />}
            >
              {hitlActioned === 'approved' ? 'Approved' : 'Denied'}
            </Label>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <Button
              variant="primary"
              size="sm"
              icon={<CheckCircleIcon />}
              style={{ backgroundColor: 'var(--pf-v5-global--success-color--100)' }}
              onClick={() => {
                setHitlActioned('approved');
                onApprove?.();
              }}
            >
              Approve
            </Button>
            <Button
              variant="danger"
              size="sm"
              icon={<TimesCircleIcon />}
              onClick={() => {
                setHitlActioned('denied');
                onDeny?.();
              }}
            >
              Deny
            </Button>
          </div>
        )}
      </div>
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
            title={msg.timestamp.toLocaleString()}
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

// ---------------------------------------------------------------------------
// SandboxPage
// ---------------------------------------------------------------------------

const STORAGE_KEY_SESSION = 'kagenti-sandbox-last-session';
const STORAGE_KEY_NAMESPACE = 'kagenti-sandbox-last-namespace';

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
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [oldestIndex, setOldestIndex] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { getToken, user } = useAuth();
  const currentUsername = user?.username || 'you';
  const [selectedAgent, setSelectedAgent] = useState('sandbox-legion');
  const [agentLoops, setAgentLoops] = useState<Map<string, AgentLoop>>(new Map());
  const [skillWhispererDismissed, setSkillWhispererDismissed] = useState(false);
  const [activeTab, setActiveTab] = useState<string>(() => searchParams.get('tab') || 'chat');
  // SandboxConfig disabled — model/repo/branch not yet wired to backend
  // const [config, setConfig] = useState({ model: 'gpt-4o-mini', repo: '', branch: 'main' });

  // Fetch agent card to get skills for / autocomplete
  const { data: agentCard } = useQuery({
    queryKey: ['agent-card', namespace, selectedAgent],
    queryFn: () => chatService.getAgentCard(namespace, selectedAgent),
    enabled: !!namespace && !!selectedAgent,
    staleTime: 60000,
    retry: 1,
  });
  const agentSkills = agentCard?.skills || [];

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

    // Only treat as tool data if it's an explicit tool call/result/thinking event
    const toolTypes = ['tool_call', 'tool_result', 'thinking', 'hitl_request', 'hitl_response', 'graph_event'];
    if (firstPart?.kind === 'data' && toolTypes.includes(firstPart?.type as string)) {
      return {
        id: `history-${h._index ?? i}`,
        role: h.role as 'user' | 'assistant',
        content: '',
        timestamp: new Date(),
        toolData: firstPart as unknown as ToolCallData,
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
      id: `history-${h._index ?? i}`,
      role: h.role as 'user' | 'assistant',
      content,
      timestamp: new Date(),
      username: h.username || (h.metadata?.username as string | undefined),
    };
  };

  /** Load the initial (most recent) page of history. */
  const loadInitialHistory = useCallback(
    async (ns: string, ctxId: string) => {
      if (!ns || !ctxId) return;
      setLoadingHistory(true);
      try {
        const page = await sandboxService.getHistory(ns, ctxId, {
          limit: INITIAL_HISTORY_LIMIT,
        });
        setMessages(page.messages.map(toMessage));
        setHasMoreHistory(page.has_more);
        if (page.messages.length > 0) {
          setOldestIndex(page.messages[0]._index ?? 0);
        }
      } catch {
        // Fallback: endpoint may not exist on older backends
        try {
          const detail = await sandboxService.getSession(ns, ctxId);
          if (detail?.history) {
            const filtered = detail.history.filter((h) => {
              if (h.role === 'user') return true;
              const text =
                h.parts?.map((p) => p.text).filter(Boolean).join('') || '';
              return text ? !isGraphDump(text) : false;
            });
            setMessages(filtered.slice(-INITIAL_HISTORY_LIMIT).map(toMessage));
            setHasMoreHistory(filtered.length > INITIAL_HISTORY_LIMIT);
          }
        } catch {
          // ignore
        }
      } finally {
        setLoadingHistory(false);
      }
    },
    []
  );

  // Load history on session change + sync URL if restored from localStorage
  useEffect(() => {
    if (contextId && namespace) {
      loadInitialHistory(namespace, contextId);
      // Sync URL if session was restored from localStorage
      if (!searchParams.get('session') && contextId) {
        setSearchParams({ session: contextId }, { replace: true });
      }
    }
  }, [contextId, namespace, loadInitialHistory, searchParams, setSearchParams]);

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
    (id: string) => {
      setContextId(id);
      setMessages([]);
      setAgentLoops(new Map());
      setInput('');
      setStreamingContent('');
      setIsStreaming(false);
      setError(null);
      setHasMoreHistory(false);
      setOldestIndex(null);
      shouldAutoScroll.current = true;
      if (id) {
        setSearchParams({ session: id });
        localStorage.setItem(STORAGE_KEY_SESSION, id);
      } else {
        setSearchParams({});
        localStorage.removeItem(STORAGE_KEY_SESSION);
      }
    },
    [setSearchParams]
  );

  /** Start a new session with the chosen agent (from the New Session modal). */
  const handleNewSession = useCallback(
    (agentName: string) => {
      setSelectedAgent(agentName);
      handleSelectSession(''); // clears contextId, URL params, messages
    },
    [handleSelectSession]
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
      session_id: contextId || undefined,
      agent_name: selectedAgent,
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
        },
      ]);
    }
  };

  /** Update or create an AgentLoop in the loops map. */
  const updateLoop = useCallback((loopId: string, updater: (prev: AgentLoop) => AgentLoop) => {
    setAgentLoops((prev) => {
      const next = new Map(prev);
      const existing = next.get(loopId) || {
        id: loopId,
        status: 'planning' as const,
        model: '',
        plan: [],
        currentStep: 0,
        totalSteps: 0,
        iteration: 0,
        steps: [],
        budget: { tokensUsed: 0, tokensBudget: 0, wallClockS: 0, maxWallClockS: 0 },
      };
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
    const body: Record<string, unknown> = {
      message: messageToSend,
      session_id: contextId || undefined,
      agent_name: selectedAgent,
    };
    if (skill) body.skill = skill;
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
    const collectedMessages: Message[] = [];

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
              setSearchParams({ session: data.session_id });
              localStorage.setItem(STORAGE_KEY_SESSION, data.session_id);
            }

            // Handle agent loop events (grouped by loop_id)
            // The backend forwards loop events with loop_id at top level
            // and the full event in data.loop_event
            if (data.loop_id) {
              const loopId = data.loop_id;
              const le = data.loop_event || data;
              const eventType = le.type;

              if (eventType === 'plan') {
                updateLoop(loopId, (l) => ({
                  ...l,
                  status: 'planning',
                  plan: le.steps || [],
                  totalSteps: (le.steps || []).length,
                  iteration: le.iteration ?? l.iteration,
                  model: le.model || l.model,
                }));
              } else if (eventType === 'plan_step') {
                updateLoop(loopId, (l) => ({
                  ...l,
                  status: 'executing',
                  currentStep: le.step ?? l.currentStep,
                  totalSteps: le.total_steps ?? l.totalSteps,
                  model: le.model || l.model,
                  steps: [
                    ...l.steps.filter((s: { index: number }) => s.index !== le.step),
                    {
                      index: le.step,
                      description: le.description || '',
                      model: le.model || l.model,
                      tokens: { prompt: 0, completion: 0 },
                      toolCalls: [],
                      toolResults: [],
                      durationMs: 0,
                      status: 'running' as const,
                    },
                  ],
                }));
              } else if (eventType === 'tool_call') {
                updateLoop(loopId, (l) => {
                  const stepIdx = le.step ?? l.currentStep;
                  const steps = [...l.steps];
                  const step = steps.find((s: { index: number }) => s.index === stepIdx);
                  if (step) {
                    step.toolCalls = [...step.toolCalls, ...(le.tools || [{ type: 'tool_call', name: le.name, args: le.args }])];
                  }
                  return { ...l, steps, model: le.model || l.model };
                });
              } else if (eventType === 'tool_result') {
                updateLoop(loopId, (l) => {
                  const stepIdx = le.step ?? l.currentStep;
                  const steps = [...l.steps];
                  const step = steps.find((s: { index: number }) => s.index === stepIdx);
                  if (step) {
                    step.toolResults = [...step.toolResults, { type: 'tool_result', name: le.name, output: le.output }];
                    step.status = 'done';
                  }
                  return { ...l, steps };
                });
              } else if (eventType === 'reflection') {
                updateLoop(loopId, (l) => ({
                  ...l,
                  status: 'reflecting',
                  reflection: le.assessment || '',
                  iteration: le.iteration ?? l.iteration,
                  model: le.model || l.model,
                }));
              } else if (eventType === 'budget') {
                updateLoop(loopId, (l) => ({
                  ...l,
                  budget: {
                    tokensUsed: le.tokens_used ?? l.budget.tokensUsed,
                    tokensBudget: le.tokens_budget ?? l.budget.tokensBudget,
                    wallClockS: le.wall_clock_s ?? l.budget.wallClockS,
                    maxWallClockS: le.max_wall_clock_s ?? l.budget.maxWallClockS,
                  },
                }));
              } else if (eventType === 'llm_response') {
                updateLoop(loopId, (l) => ({
                  ...l,
                  status: 'done',
                  finalAnswer: le.content || '',
                  model: le.model || l.model,
                }));
              }

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
            if (data.event && data.event.message) {
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
                    toolData: parsed,
                  });
                  hadToolEvents = true;
                }
              }
              // Flush tool call events immediately so they render during streaming.
              // Snapshot the items BEFORE passing to the updater — React StrictMode
              // may invoke updater functions twice, so splice() inside would lose
              // items on the second invocation.
              if (hadToolEvents) {
                const snapshot = collectedMessages.splice(0);
                setMessages((prev) => [...prev, ...snapshot]);
              }
            }

            // Accumulate content for real-time display (final answer)
            if (data.content) {
              accumulatedContent += data.content;
              setStreamingContent(accumulatedContent);
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
    // Snapshot collectedMessages for the same StrictMode reason as above.
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
        },
      ]);
    }

    return true;
  };

  const handleSendMessage = async () => {
    if (!input.trim() || isStreaming) return;

    shouldAutoScroll.current = true;

    // Parse /skill:name prefix from message (e.g. "/rca:ci #758" → skill="rca:ci", text="#758")
    const trimmed = input.trim();
    const skillMatch = trimmed.match(/^\/([\w:.-]+)\s*(.*)/s);
    const skill = skillMatch ? skillMatch[1] : undefined;
    const messageText = skillMatch ? (skillMatch[2] || skillMatch[1]) : trimmed;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
      username: currentUsername,
    };
    setMessages((prev) => [...prev, userMessage]);
    const messageToSend = messageText;
    setInput('');
    setIsStreaming(true);
    setStreamingContent('');
    setError(null);

    try {
      const token = await getToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      // Try streaming first; fall back to non-streaming on failure
      let streamed = false;
      try {
        streamed = await sendStreaming(messageToSend, headers, skill);
      } catch (streamErr) {
        // Streaming failed — check if it's a connection error
        const streamMsg = streamErr instanceof Error ? streamErr.message : '';
        if (streamMsg.includes('connection') || streamMsg.includes('chunked')) {
          throw streamErr; // Let the outer catch handle with backoff
        }
        // Other errors: fall through to non-streaming
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
          },
        ]);
      }
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
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
          {!contextId && (
            <SandboxAgentsPanel
              namespace={namespace}
              selectedAgent={selectedAgent}
              onSelectAgent={(name) => setSelectedAgent(name || 'sandbox-legion')}
            />
          )}
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
            </SplitItem>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Namespace:</span>
              <Tooltip content="Kubernetes namespace where the agent runs">
                <Label isCompact color="blue">{namespace}</Label>
              </Tooltip>
            </SplitItem>
            <SplitItem>
              <span style={{ fontSize: '0.9em', color: 'var(--pf-v5-global--Color--200)', marginRight: 4 }}>Model:</span>
              <Tooltip content="LLM model used by this agent">
                <Label isCompact color="orange" icon={<CogIcon />}>
                  {(agentCard as Record<string, unknown>)?.model as string || 'llama4-scout'}
                </Label>
              </Tooltip>
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
            <SplitItem>
              <Button
                variant="link"
                component="a"
                href={`/sandbox/files/${namespace}/${selectedAgent}`}
                icon={<FolderOpenIcon />}
                isDisabled={!selectedAgent}
              >
                Files
              </Button>
            </SplitItem>
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

          <Tabs
            activeKey={activeTab}
            onSelect={(_e, key) => {
              const tab = String(key);
              setActiveTab(tab);
              setSearchParams(prev => {
                const next = new URLSearchParams(prev);
                next.set('tab', tab);
                return next;
              }, { replace: true });
            }}
            isBox={false}
            style={{ flex: 1, minHeight: 0 }}
          >
            <Tab eventKey="chat" title={<TabTitleText>Chat</TabTitleText>}>

          {/* Chat messages */}
          <Card style={{ flex: 1, overflow: 'hidden' }}>
            <CardBody
              ref={scrollContainerRef}
              style={{
                height: '100%',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                padding: '12px 16px',
              }}
            >
              {/* Sentinel for infinite scroll — loads older messages */}
              <div ref={sentinelRef} style={{ minHeight: 1 }} />
              {loadingHistory && (
                <div style={{ textAlign: 'center', padding: 8 }}>
                  <Spinner size="sm" />
                </div>
              )}

              {/* Welcome card — permanent first message */}
              <div
                data-testid="welcome-card"
                style={{
                  display: 'flex',
                  alignItems: messages.length === 0 ? 'center' : 'flex-start',
                  justifyContent: 'center',
                  padding: messages.length === 0 ? 32 : '12px 14px',
                  flex: messages.length === 0 ? 1 : undefined,
                }}
              >
                <div style={{ maxWidth: 480, textAlign: 'center' }}>
                  {/* Agent avatar + name */}
                  <div
                    style={{
                      width: messages.length === 0 ? 48 : 32,
                      height: messages.length === 0 ? 48 : 32,
                      borderRadius: '50%',
                      backgroundColor: 'var(--pf-v5-global--success-color--100)',
                      color: '#fff',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: messages.length === 0 ? 20 : 14,
                      marginBottom: messages.length === 0 ? 12 : 6,
                    }}
                  >
                    <RobotIcon />
                  </div>
                  <h3 style={{ margin: '0 0 4px', fontSize: messages.length === 0 ? '1.1em' : '0.9em' }}>{selectedAgent}</h3>
                  <p style={{ margin: '0 0 8px', fontSize: '0.8em', color: 'var(--pf-v5-global--Color--200)' }}>
                    {(agentCard as Record<string, unknown>)?.model as string || 'llama4-scout'} &middot; {namespace}
                  </p>

                    {/* Available tools + example prompts — only when no messages */}
                    {messages.length === 0 && !isStreaming && (
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

              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  msg={msg}
                  currentUsername={currentUsername}
                  namespace={namespace}
                  agentName={selectedAgent}
                  onApprove={msg.toolData?.type === 'hitl_request' ? handleHitlApprove : undefined}
                  onDeny={msg.toolData?.type === 'hitl_request' ? handleHitlDeny : undefined}
                />
              ))}

              {/* Agent loop cards (collapsed agent turns) */}
              {Array.from(agentLoops.values()).map((loop) => (
                <AgentLoopCard key={loop.id} loop={loop} isStreaming={isStreaming} />
              ))}

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
                isDisabled={isStreaming}
              />
            </SplitItem>
            <SplitItem>
              <Button
                variant="primary"
                onClick={handleSendMessage}
                isDisabled={isStreaming || !input.trim()}
                icon={<PaperPlaneIcon />}
              >
                Send
              </Button>
            </SplitItem>
          </Split>

            </Tab>
            <Tab eventKey="stats" title={<TabTitleText>Stats</TabTitleText>}>
              <SessionStatsPanel
                agentLoops={agentLoops}
                messages={messages}
              />
            </Tab>
            <Tab eventKey="files" title={<TabTitleText>Files</TabTitleText>}>
              <div style={{ padding: 16, color: 'var(--pf-v5-global--Color--200)' }}>
                Open the file browser via the <strong>Files</strong> button in the header bar above.
              </div>
            </Tab>
          </Tabs>

        </div>
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
    </PageSection>
  );
};
