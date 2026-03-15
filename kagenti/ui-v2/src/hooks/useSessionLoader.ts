// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * useSessionLoader — state-machine hook for sandbox session lifecycle.
 *
 * Replaces the fragile polling-based message loading in SandboxPage.tsx
 * with a clean useReducer state machine. Phases:
 *
 *   IDLE → LOADING → LOADED ⇄ SUBSCRIBING → RECOVERING
 *
 * The hook manages data lifecycle only — it does NOT render anything.
 */

import { useReducer, useEffect, useRef, type Dispatch, type MutableRefObject } from 'react';
import { sandboxService } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import type { AgentLoop } from '../types/agentLoop';
import type { LoopEvent } from '../utils/loopBuilder';
import { applyLoopEvent, buildAgentLoops, createDefaultAgentLoop } from '../utils/loopBuilder';
import { pairMessagesWithLoops } from '../utils/historyPairing';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolCallData {
  type: 'tool_call' | 'tool_result' | 'thinking' | 'llm_response' | 'error' | 'hitl_request'
    | 'delegation_start' | 'delegation_progress' | 'delegation_complete';
  name?: string;
  args?: string | Record<string, unknown>;
  output?: string;
  content?: string;
  message?: string;
  command?: string;
  reason?: string;
  tools?: Array<{ name: string; args: string | Record<string, unknown> }>;
  child_context_id?: string;
  delegation_mode?: string;
  task?: string;
  variant?: string;
  state?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolData?: ToolCallData;
  username?: string;
  /** Stable sort key from the backend (_index) or insertion order. */
  order: number;
}

export type Phase = 'IDLE' | 'LOADING' | 'LOADED' | 'SUBSCRIBING' | 'RECOVERING';

// ---------------------------------------------------------------------------
// State & Actions
// ---------------------------------------------------------------------------

interface SessionState {
  phase: Phase;
  messages: Message[];
  agentLoops: Map<string, AgentLoop>;
  hasMoreHistory: boolean;
  oldestIndex: number | null;
  error: string | null;
  recoveryAttempts: number;
}

/** Detect and filter out LangGraph intermediate status dumps and JSON loop events from history. */
function isGraphDump(text: string): boolean {
  const t = text.trim();
  if (/^(assistant|tools|__end__):\s/m.test(t)) return true;
  try {
    const parsed = JSON.parse(t);
    if (parsed && typeof parsed === 'object' && parsed.type && parsed.loop_id) return true;
  } catch { /* not JSON */ }
  return false;
}

/** Number of history messages to show initially; rest behind "Load earlier". */
const INITIAL_HISTORY_LIMIT = 30;

const TERMINAL_STATES = new Set(['completed', 'failed', 'canceled', 'rejected']);

const RECOVERY_DELAYS = [1000, 2000, 4000, 8000, 15000];

type Action =
  | { type: 'SESSION_SELECTED' }
  | {
      type: 'HISTORY_LOADED';
      messages: Message[];
      agentLoops: Map<string, AgentLoop>;
      hasMoreHistory: boolean;
      oldestIndex: number | null;
      isTerminal: boolean;
    }
  | { type: 'LOOP_EVENT'; event: LoopEvent; userMessage?: string }
  | { type: 'SUBSCRIBE_DONE' }
  | { type: 'SUBSCRIBE_ERROR' }
  | { type: 'RECOVERY_RESULT'; isTerminal: boolean; agentLoops?: Map<string, AgentLoop> }
  | { type: 'SESSION_CLEARED' }
  | { type: 'SEND_STARTED' }
  | { type: 'SEND_DONE' }
  | {
      type: 'MESSAGES_PREPENDED';
      messages: Message[];
      oldestIndex: number | null;
      hasMoreHistory: boolean;
    }
  | { type: 'MESSAGES_APPENDED'; messages: Message[] }
  | { type: 'MESSAGES_SET'; messages: Message[] }
  | {
      type: 'LOOPS_UPDATE';
      updater: (prev: Map<string, AgentLoop>) => Map<string, AgentLoop>;
    }
  | {
      type: 'LOOP_CANCEL';
    };

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function sessionReducer(state: SessionState, action: Action): SessionState {
  switch (action.type) {
    case 'SESSION_SELECTED':
      return {
        ...state,
        phase: 'LOADING',
        messages: [],
        agentLoops: new Map(),
        hasMoreHistory: false,
        oldestIndex: null,
        error: null,
        recoveryAttempts: 0,
      };

    case 'HISTORY_LOADED':
      return {
        ...state,
        phase: action.isTerminal ? 'LOADED' : 'SUBSCRIBING',
        messages: action.messages,
        agentLoops: action.agentLoops,
        hasMoreHistory: action.hasMoreHistory,
        oldestIndex: action.oldestIndex,
        error: null,
        recoveryAttempts: 0,
      };

    case 'LOOP_EVENT': {
      const loopId = action.event.loop_id;
      if (!loopId) return state;
      const next = new Map(state.agentLoops);
      let existing = next.get(loopId);
      if (!existing) {
        existing = createDefaultAgentLoop(loopId);
        if (action.userMessage) {
          existing.userMessage = action.userMessage;
        }
      }
      next.set(loopId, applyLoopEvent(existing, action.event));
      return { ...state, agentLoops: next };
    }

    case 'SUBSCRIBE_DONE': {
      // Mark all loops as done or failed when stream completes
      const finalized = new Map(state.agentLoops);
      for (const [id, loop] of finalized) {
        if (loop.status === 'done') continue;
        if (loop.finalAnswer) {
          finalized.set(id, { ...loop, status: 'done' });
        } else {
          finalized.set(id, {
            ...loop,
            status: 'failed',
            failureReason: loop.failureReason || 'Agent stopped without producing a final answer.',
          });
        }
      }
      return { ...state, phase: 'LOADED', agentLoops: finalized };
    }

    case 'SUBSCRIBE_ERROR':
      return {
        ...state,
        phase: 'RECOVERING',
        recoveryAttempts: state.recoveryAttempts + 1,
      };

    case 'RECOVERY_RESULT': {
      if (action.isTerminal) {
        // Session finished while we were disconnected
        const loops = action.agentLoops || state.agentLoops;
        return {
          ...state,
          phase: 'LOADED',
          agentLoops: loops,
          error: null,
          recoveryAttempts: 0,
        };
      }
      // Session still active — reconnect
      return {
        ...state,
        phase: 'SUBSCRIBING',
        agentLoops: action.agentLoops || state.agentLoops,
        error: null,
      };
    }

    case 'SESSION_CLEARED':
      return {
        phase: 'IDLE',
        messages: [],
        agentLoops: new Map(),
        hasMoreHistory: false,
        oldestIndex: null,
        error: null,
        recoveryAttempts: 0,
      };

    case 'SEND_STARTED':
      return { ...state, phase: 'SUBSCRIBING', error: null };

    case 'SEND_DONE': {
      // Mark loops as done/executing based on whether they have a final answer
      const doneLoops = new Map(state.agentLoops);
      for (const [id, loop] of doneLoops) {
        if (loop.status === 'done') continue;
        if (loop.finalAnswer) {
          doneLoops.set(id, { ...loop, status: 'done' });
        } else {
          doneLoops.set(id, { ...loop, status: 'executing' });
        }
      }
      return { ...state, phase: 'LOADED', agentLoops: doneLoops };
    }

    case 'MESSAGES_PREPENDED':
      return {
        ...state,
        messages: [...action.messages, ...state.messages],
        oldestIndex: action.oldestIndex,
        hasMoreHistory: action.hasMoreHistory,
      };

    case 'MESSAGES_APPENDED':
      return {
        ...state,
        messages: [...state.messages, ...action.messages],
      };

    case 'MESSAGES_SET':
      return {
        ...state,
        messages: action.messages,
      };

    case 'LOOPS_UPDATE': {
      const updated = action.updater(state.agentLoops);
      return updated === state.agentLoops ? state : { ...state, agentLoops: updated };
    }

    case 'LOOP_CANCEL': {
      const canceled = new Map(state.agentLoops);
      for (const [id, loop] of canceled) {
        if (loop.status !== 'done') {
          canceled.set(id, { ...loop, status: 'canceled' });
        }
      }
      return { ...state, phase: 'LOADED', agentLoops: canceled };
    }

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Helper: convert a history message to Message
// ---------------------------------------------------------------------------

function toMessage(
  h: { role: string; parts?: Array<Record<string, unknown>>; _index?: number; username?: string; metadata?: Record<string, unknown> },
  i: number,
): Message {
  const firstPart = h.parts?.[0] as Record<string, unknown> | undefined;
  const order = h._index ?? i;

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

  const content = h.parts
    ?.map((p) => {
      if (typeof p.text === 'string') return p.text;
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
}

// ---------------------------------------------------------------------------
// Shared fetch helper — DRY for Effects 1, 4, and signal gating
// ---------------------------------------------------------------------------

interface FetchResult {
  messages: Message[];
  agentLoops: Map<string, AgentLoop>;
  hasMoreHistory: boolean;
  oldestIndex: number | null;
  isTerminal: boolean;
}

/**
 * Fetch session detail + history page and build messages/loops.
 * Used by initial load, status-poll reload, and signal-gated reload.
 */
async function fetchAndBuildHistory(
  ns: string,
  ctxId: string,
): Promise<FetchResult> {
  const [sessionDetail, historyPage] = await Promise.all([
    sandboxService.getSession(ns, ctxId).catch(() => null),
    sandboxService.getHistory(ns, ctxId, { limit: INITIAL_HISTORY_LIMIT }).catch(() => null),
  ]);

  let finalMessages: Message[] = [];
  let finalLoops = new Map<string, AgentLoop>();
  let hasMore = false;
  let oldest: number | null = null;
  let isTerminal = false;

  if (historyPage) {
    const allMessages = historyPage.messages.map(toMessage);
    hasMore = historyPage.has_more;
    if (historyPage.messages.length > 0) {
      oldest = historyPage.messages[0]._index ?? 0;
    }

    // Determine terminal state
    const taskState = historyPage.task_state
      || (sessionDetail?.status as Record<string, unknown> | undefined)?.state as string | undefined;
    isTerminal = !!taskState && TERMINAL_STATES.has(taskState);

    // Build loops from events
    if (historyPage.loop_events && historyPage.loop_events.length > 0) {
      const events = historyPage.loop_events as unknown as LoopEvent[];
      finalLoops = buildAgentLoops(events);

      // Pair user messages with loops
      const loopArr = Array.from(finalLoops.values());
      const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(
        allMessages.map((m) => ({ role: m.role, content: m.content, order: m.order })),
        loopArr,
      );
      for (const paired of pairedLoops) {
        finalLoops.set(paired.id, paired);
      }
      finalMessages = unpairedMessages.map((um, idx) => ({
        id: `unpaired-${idx}`,
        role: um.role as 'user' | 'assistant',
        content: um.content,
        timestamp: new Date(),
        order: um.order,
      }));

      // If all loops have a final answer and session is not terminal, treat as loaded
      const hasComplete = Array.from(finalLoops.values()).some((l) => l.finalAnswer);
      if (hasComplete && !isTerminal) {
        isTerminal = true;
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
    isTerminal = true; // old-style sessions without loop events
  }

  return { messages: finalMessages, agentLoops: finalLoops, hasMoreHistory: hasMore, oldestIndex: oldest, isTerminal };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseSessionLoaderReturn {
  phase: Phase;
  messages: Message[];
  agentLoops: Map<string, AgentLoop>;
  hasMoreHistory: boolean;
  oldestIndex: number | null;
  error: string | null;
  isLoading: boolean;
  isStreaming: boolean;
  dispatch: Dispatch<Action>;
  subscribeAbortRef: MutableRefObject<AbortController | null>;
}

export function useSessionLoader(
  namespace: string,
  contextId: string,
): UseSessionLoaderReturn {
  const { getToken } = useAuth();
  const subscribeAbortRef = useRef<AbortController | null>(null);
  const pendingReloadSignal = useRef(false);

  const [state, dispatch] = useReducer(sessionReducer, {
    phase: 'IDLE',
    messages: [],
    agentLoops: new Map(),
    hasMoreHistory: false,
    oldestIndex: null,
    error: null,
    recoveryAttempts: 0,
  });

  // ----- Effect 1: contextId changes → fetch session + history -----
  useEffect(() => {
    if (!contextId || !namespace) {
      // contextId cleared → reset to IDLE
      if (state.phase !== 'IDLE') {
        dispatch({ type: 'SESSION_CLEARED' });
      }
      return;
    }

    // Cancel any existing SSE before loading new session
    if (subscribeAbortRef.current) {
      subscribeAbortRef.current.abort();
      subscribeAbortRef.current = null;
    }

    dispatch({ type: 'SESSION_SELECTED' });

    let cancelled = false;

    (async () => {
      try {
        const result = await fetchAndBuildHistory(namespace, contextId);
        if (cancelled) return;

        dispatch({
          type: 'HISTORY_LOADED',
          messages: result.messages,
          agentLoops: result.agentLoops,
          hasMoreHistory: result.hasMoreHistory,
          oldestIndex: result.oldestIndex,
          isTerminal: result.isTerminal,
        });
      } catch (err) {
        if (cancelled) return;
        console.error('[useSessionLoader] Failed to load session:', err);
        dispatch({
          type: 'HISTORY_LOADED',
          messages: [],
          agentLoops: new Map(),
          hasMoreHistory: false,
          oldestIndex: null,
          isTerminal: true,
        });
      }
    })();

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextId, namespace]);

  // ----- Effect 2: SUBSCRIBING phase → open SSE -----
  useEffect(() => {
    if (state.phase !== 'SUBSCRIBING' || !contextId || !namespace) return;

    // Cancel any existing SSE
    if (subscribeAbortRef.current) {
      subscribeAbortRef.current.abort();
    }
    const controller = new AbortController();
    subscribeAbortRef.current = controller;

    let cancelled = false;

    (async () => {
      try {
        const token = await getToken();
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const url = `/api/v1/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/subscribe`;
        const response = await fetch(url, { headers, signal: controller.signal });

        if (!response.ok || !response.body) {
          if (!cancelled) {
            console.log('[useSessionLoader:subscribe] Not available or session completed');
            dispatch({ type: 'SUBSCRIBE_DONE' });
          }
          return;
        }

        console.log('[useSessionLoader:subscribe] Connected to live stream');
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
                if (data.done) {
                  if (!cancelled) dispatch({ type: 'SUBSCRIBE_DONE' });
                  return;
                }
                if (data.ping) continue;
                if (data.loop_id && data.loop_event) {
                  const evt = data.loop_event as LoopEvent;
                  evt.loop_id = evt.loop_id || data.loop_id;
                  if (!cancelled) {
                    dispatch({ type: 'LOOP_EVENT', event: evt });
                  }
                }
              } catch {
                // skip parse errors
              }
            }
          }
        } finally {
          reader.releaseLock();
        }

        // Reader ended normally (stream closed)
        if (!cancelled) dispatch({ type: 'SUBSCRIBE_DONE' });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === 'AbortError') {
          console.log('[useSessionLoader:subscribe] Aborted');
          return;
        }
        console.warn('[useSessionLoader:subscribe] Error:', err);
        dispatch({ type: 'SUBSCRIBE_ERROR' });
      } finally {
        if (subscribeAbortRef.current === controller) {
          subscribeAbortRef.current = null;
        }
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
      if (subscribeAbortRef.current === controller) {
        subscribeAbortRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, contextId, namespace]);

  // ----- Effect 3: RECOVERING phase → exponential backoff -----
  useEffect(() => {
    if (state.phase !== 'RECOVERING' || !contextId || !namespace) return;

    if (state.recoveryAttempts > RECOVERY_DELAYS.length) {
      // Max retries exceeded — give up and transition to LOADED with error
      dispatch({
        type: 'HISTORY_LOADED',
        messages: state.messages,
        agentLoops: state.agentLoops,
        hasMoreHistory: state.hasMoreHistory,
        oldestIndex: state.oldestIndex,
        isTerminal: true,
      });
      return;
    }

    const delay = RECOVERY_DELAYS[Math.min(state.recoveryAttempts - 1, RECOVERY_DELAYS.length - 1)];
    let cancelled = false;

    const timer = setTimeout(async () => {
      if (cancelled) return;
      try {
        const historyPage = await sandboxService.getHistory(namespace, contextId, {
          limit: INITIAL_HISTORY_LIMIT,
        });

        if (cancelled) return;

        const taskState = historyPage.task_state;
        const isTerminal = !!taskState && TERMINAL_STATES.has(taskState);

        // Rebuild loops from fresh events
        let recoveredLoops = state.agentLoops;
        if (historyPage.loop_events && historyPage.loop_events.length > 0) {
          recoveredLoops = buildAgentLoops(historyPage.loop_events as unknown as LoopEvent[]);
        }

        dispatch({
          type: 'RECOVERY_RESULT',
          isTerminal,
          agentLoops: recoveredLoops,
        });
      } catch {
        if (cancelled) return;
        // Recovery fetch failed — re-dispatch SUBSCRIBE_ERROR to increment
        // the attempt counter and schedule another retry.
        dispatch({ type: 'SUBSCRIBE_ERROR' });
      }
    }, delay);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, state.recoveryAttempts, contextId, namespace]);

  // ----- Effect 4: 30s session status poll (LOADED phase only) -----
  useEffect(() => {
    if (state.phase !== 'LOADED' || !contextId || !namespace) return;

    const interval = setInterval(async () => {
      try {
        const session = await sandboxService.getSession(namespace, contextId);
        const taskState = (session?.status as unknown as Record<string, unknown> | undefined)?.state as string | undefined;

        if (taskState && !TERMINAL_STATES.has(taskState)) {
          // Session is active again — need to reload
          pendingReloadSignal.current = true;
          dispatch({ type: 'SESSION_SELECTED' });

          try {
            const result = await fetchAndBuildHistory(namespace, contextId);
            dispatch({
              type: 'HISTORY_LOADED',
              messages: result.messages,
              agentLoops: result.agentLoops,
              hasMoreHistory: result.hasMoreHistory,
              oldestIndex: result.oldestIndex,
              isTerminal: false, // Active session → subscribe
            });
          } catch {
            // Re-fetch failed — stay in LOADING
          }
        }
      } catch {
        // Poll failure is non-critical
      }
    }, 30000);

    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, contextId, namespace]);

  // ----- Signal gating: check pendingReloadSignal on SUBSCRIBE_DONE -----
  // When the phase transitions to LOADED from SUBSCRIBING, check if a
  // reload was requested during the subscription.
  const prevPhaseRef = useRef<Phase>(state.phase);
  useEffect(() => {
    const prevPhase = prevPhaseRef.current;
    prevPhaseRef.current = state.phase;

    if (prevPhase === 'SUBSCRIBING' && state.phase === 'LOADED' && pendingReloadSignal.current) {
      pendingReloadSignal.current = false;
      if (contextId && namespace) {
        dispatch({ type: 'SESSION_SELECTED' });
        (async () => {
          try {
            const result = await fetchAndBuildHistory(namespace, contextId);
            dispatch({
              type: 'HISTORY_LOADED',
              messages: result.messages,
              agentLoops: result.agentLoops,
              hasMoreHistory: result.hasMoreHistory,
              oldestIndex: result.oldestIndex,
              isTerminal: result.isTerminal,
            });
          } catch {
            // Reload failed — stay in current state
          }
        })();
      }
    }
  }, [state.phase, contextId, namespace]);

  return {
    phase: state.phase,
    messages: state.messages,
    agentLoops: state.agentLoops,
    hasMoreHistory: state.hasMoreHistory,
    oldestIndex: state.oldestIndex,
    error: state.error,
    isLoading: state.phase === 'LOADING',
    isStreaming: state.phase === 'SUBSCRIBING',
    dispatch,
    subscribeAbortRef,
  };
}

export type { Action as SessionAction };
