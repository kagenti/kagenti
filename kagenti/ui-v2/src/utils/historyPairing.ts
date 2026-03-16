// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Pair user messages with AgentLoop objects for historical rendering.
 *
 * When a session has loop_events, user messages are paired with loops
 * so that each loop card displays its triggering user message. This
 * avoids rendering flat ChatBubbles separately from loop cards.
 */

import type { AgentLoop } from '../types/agentLoop';

/** Minimal message shape needed for pairing. */
export interface PairableMessage {
  role: string;
  content: string;
  order: number;
  /** Optional task_id for task-based pairing. */
  taskId?: string;
}

/**
 * Pair user messages with loops by task_id first, then chronological order.
 *
 * Strategy:
 *   1. If a message has a taskId matching a loop's id, pair directly.
 *   2. Otherwise fall back to chronological position pairing.
 *
 * Messages are sorted by their `order` field (derived from backend `_index`)
 * to ensure correct pairing regardless of DB row order. Each user message
 * is assigned to the loop at the same position.
 *
 * Returns the loops with `userMessage` set, plus any unpaired messages
 * (assistant messages, or user messages beyond the number of loops).
 */
export function pairMessagesWithLoops(
  messages: PairableMessage[],
  loops: AgentLoop[],
): { pairedLoops: AgentLoop[]; unpairedMessages: PairableMessage[] } {
  const userMsgs = messages
    .filter((m) => m.role === 'user')
    .sort((a, b) => a.order - b.order);

  const nonUserMsgs = messages.filter((m) => m.role !== 'user');

  // Build a lookup of loop id -> index for task_id matching
  const loopIdxMap = new Map<string, number>();
  loops.forEach((l, i) => loopIdxMap.set(l.id, i));

  const pairedLoops = loops.map((loop) => ({ ...loop }));
  const pairedUserIdxs = new Set<number>();

  // Pass 1: task_id matching
  userMsgs.forEach((msg, msgIdx) => {
    if (msg.taskId) {
      const loopIdx = loopIdxMap.get(msg.taskId);
      if (loopIdx != null && !pairedLoops[loopIdx].userMessage) {
        pairedLoops[loopIdx].userMessage = msg.content;
        pairedUserIdxs.add(msgIdx);
      }
    }
  });

  // Pass 2: positional fallback for remaining unpaired
  let loopCursor = 0;
  userMsgs.forEach((msg, msgIdx) => {
    if (pairedUserIdxs.has(msgIdx)) return;
    // Find next loop without a userMessage
    while (loopCursor < pairedLoops.length && pairedLoops[loopCursor].userMessage) {
      loopCursor++;
    }
    if (loopCursor < pairedLoops.length) {
      pairedLoops[loopCursor].userMessage = msg.content;
      pairedUserIdxs.add(msgIdx);
      loopCursor++;
    }
  });

  // Unpaired: user messages not matched + all non-user messages
  const unpairedUserMsgs = userMsgs.filter((_, i) => !pairedUserIdxs.has(i));
  const unpairedMessages = [...unpairedUserMsgs, ...nonUserMsgs]
    .sort((a, b) => a.order - b.order);

  return { pairedLoops, unpairedMessages };
}
