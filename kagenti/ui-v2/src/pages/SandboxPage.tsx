// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  PageSection,
  Title,
  Card,
  CardBody,
  TextArea,
  Button,
  Split,
  SplitItem,
  Spinner,
  Alert,
  Label,
} from '@patternfly/react-core';
import { PaperPlaneIcon, UserIcon, RobotIcon, CheckCircleIcon, TimesCircleIcon } from '@patternfly/react-icons';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { sandboxService } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { SessionSidebar } from '../components/SessionSidebar';
import { SandboxAgentsPanel } from '../components/SandboxAgentsPanel';
// SandboxConfig disabled — model/repo/branch not yet wired to backend
// import { SandboxConfig, SandboxConfigValues } from '../components/SandboxConfig';
import { NamespaceSelector } from '../components/NamespaceSelector';

interface ToolCallData {
  type: 'tool_call' | 'tool_result' | 'thinking' | 'llm_response' | 'error' | 'hitl_request';
  name?: string;
  args?: string | Record<string, unknown>;
  output?: string;
  content?: string;
  message?: string;
  command?: string;
  reason?: string;
  tools?: Array<{ name: string; args: string | Record<string, unknown> }>;
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

  return null;
};

const ChatBubble: React.FC<{
  msg: Message;
  currentUsername?: string;
  onApprove?: () => void;
  onDeny?: () => void;
}> = ({ msg, currentUsername, onApprove, onDeny }) => {
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
            }}
          >
            {formatMsgTime(msg.timestamp)}
          </span>
        </div>

        {/* Body */}
        {isUser ? (
          <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{msg.content}</p>
        ) : (
          <div className="sandbox-markdown" style={{ fontSize: '0.92em' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {msg.content}
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
  const [namespace, setNamespace] = useState(
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
  // SandboxConfig disabled — model/repo/branch not yet wired to backend
  // const [config, setConfig] = useState({ model: 'gpt-4o-mini', repo: '', branch: 'main' });

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

    // Check if this is a tool call/result/thinking (kind: "data")
    if (firstPart?.kind === 'data' && firstPart?.type) {
      return {
        id: `history-${h._index ?? i}`,
        role: h.role as 'user' | 'assistant',
        content: '',
        timestamp: new Date(),
        toolData: firstPart as unknown as ToolCallData,
      };
    }

    return {
      id: `history-${h._index ?? i}`,
      role: h.role as 'user' | 'assistant',
      content:
        h.parts
          ?.map((p) => p.text as string)
          .filter(Boolean)
          .join('') || '',
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

  // Persist namespace to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_NAMESPACE, namespace);
  }, [namespace]);

  /** Send via non-streaming /chat endpoint (fallback). */
  const sendNonStreaming = async (
    messageToSend: string,
    headers: Record<string, string>,
  ) => {
    const response = await fetch(
      `/api/v1/sandbox/${encodeURIComponent(namespace)}/chat`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: messageToSend,
          session_id: contextId || undefined,
          agent_name: selectedAgent,
        }),
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

  /** Attempt SSE streaming via /chat/stream, return true on success. */
  const sendStreaming = async (
    messageToSend: string,
    headers: Record<string, string>,
  ): Promise<boolean> => {
    const streamUrl = sandboxService.getStreamUrl(namespace);
    const response = await fetch(streamUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        message: messageToSend,
        session_id: contextId || undefined,
        agent_name: selectedAgent,
      }),
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
              // Show the HITL message immediately
              setMessages((prev) => [...prev, ...collectedMessages.splice(0)]);
              setStreamingContent('');
            }

            // Collect tool call/result events as separate messages
            if (data.event && data.event.message) {
              const eventText = data.event.message;
              // Try to parse as structured JSON (from LangGraphSerializer)
              for (const eventLine of eventText.split('\n')) {
                const trimmed = eventLine.trim();
                if (!trimmed) continue;
                try {
                  const parsed = JSON.parse(trimmed);
                  if (parsed.type && (parsed.type === 'tool_call' || parsed.type === 'tool_result' || parsed.type === 'llm_response')) {
                    collectedMessages.push({
                      id: `stream-event-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                      role: 'assistant',
                      content: '',
                      timestamp: new Date(),
                      toolData: parsed as ToolCallData,
                    });
                  }
                } catch {
                  // Not JSON — skip
                }
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

    // Finalize: add tool call messages first, then the final response
    if (collectedMessages.length > 0 || accumulatedContent) {
      setMessages((prev) => [
        ...prev,
        ...collectedMessages, // Tool call/result steps rendered inline
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
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
      username: currentUsername,
    };
    setMessages((prev) => [...prev, userMessage]);
    const messageToSend = input.trim();
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
        streamed = await sendStreaming(messageToSend, headers);
      } catch (streamErr) {
        // Streaming failed — check if it's a connection error
        const streamMsg = streamErr instanceof Error ? streamErr.message : '';
        if (streamMsg.includes('connection') || streamMsg.includes('chunked')) {
          throw streamErr; // Let the outer catch handle with backoff
        }
        // Other errors: fall through to non-streaming
      }

      if (!streamed) {
        await sendNonStreaming(messageToSend, headers);
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
        {/* Left column: sessions + sandbox agents */}
        <div
          style={{
            width: 280,
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            borderRight: '1px solid var(--pf-v5-global--BorderColor--100)',
          }}
        >
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <SessionSidebar
              namespace={namespace}
              activeContextId={contextId}
              onSelectSession={handleSelectSession}
            />
          </div>
          <SandboxAgentsPanel
            namespace={namespace}
            selectedAgent={selectedAgent}
            onSelectAgent={(name) => setSelectedAgent(name || 'sandbox-legion')}
          />
        </div>

        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            padding: 16,
          }}
        >
          {/* Header */}
          <Split hasGutter style={{ marginBottom: 8 }}>
            <SplitItem>
              <Title headingLevel="h1" size="xl">
                {selectedAgent}
              </Title>
            </SplitItem>
            <SplitItem isFilled />
            <SplitItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
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

              {messages.length === 0 && !isStreaming && (
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--pf-v5-global--Color--200)',
                  }}
                >
                  Start a conversation with {selectedAgent}
                </div>
              )}

              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  msg={msg}
                  currentUsername={currentUsername}
                  onApprove={msg.toolData?.type === 'hitl_request' ? handleHitlApprove : undefined}
                  onDeny={msg.toolData?.type === 'hitl_request' ? handleHitlDeny : undefined}
                />
              ))}

              {isStreaming && (
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
            <SplitItem isFilled>
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
