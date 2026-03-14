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
}

/**
 * Pair user messages with loops by chronological order.
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

  // Pair user messages with loops by position (chronological)
  const pairedLoops = loops.map((loop, i) => {
    if (i < userMsgs.length) {
      return { ...loop, userMessage: userMsgs[i].content };
    }
    return loop;
  });

  // Unpaired: user messages beyond loop count + all non-user messages
  const unpairedUserMsgs = userMsgs.slice(loops.length);
  const unpairedMessages = [...unpairedUserMsgs, ...nonUserMsgs]
    .sort((a, b) => a.order - b.order);

  return { pairedLoops, unpairedMessages };
}
