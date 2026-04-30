// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import { pairMessagesWithLoops, type PairableMessage } from './historyPairing';
import { createDefaultAgentLoop } from './loopBuilder';

function makeMsg(role: string, content: string, order: number): PairableMessage {
  return { role, content, order };
}

describe('pairMessagesWithLoops', () => {
  it('pairs single user message with single loop', () => {
    const messages = [makeMsg('user', 'Analyze CI failures', 0)];
    const loops = [createDefaultAgentLoop('L1')];

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops).toHaveLength(1);
    expect(pairedLoops[0].userMessage).toBe('Analyze CI failures');
    expect(unpairedMessages).toHaveLength(0);
  });

  it('pairs 2 user messages with 2 loops in order', () => {
    const messages = [
      makeMsg('user', 'Initial request', 0),
      makeMsg('user', 'continue', 5),
    ];
    const loops = [createDefaultAgentLoop('L1'), createDefaultAgentLoop('L2')];

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops).toHaveLength(2);
    expect(pairedLoops[0].userMessage).toBe('Initial request');
    expect(pairedLoops[1].userMessage).toBe('continue');
    expect(unpairedMessages).toHaveLength(0);
  });

  it('sorts messages by order before pairing (handles reversed DB order)', () => {
    // "continue" has lower _index due to DB row order, but higher chronological order
    const messages = [
      makeMsg('user', 'continue', 10),    // chronologically second
      makeMsg('user', 'Initial request', 2), // chronologically first
    ];
    const loops = [createDefaultAgentLoop('L1'), createDefaultAgentLoop('L2')];

    const { pairedLoops } = pairMessagesWithLoops(messages, loops);

    // Should pair by chronological order, not array position
    expect(pairedLoops[0].userMessage).toBe('Initial request');
    expect(pairedLoops[1].userMessage).toBe('continue');
  });

  it('handles 3 loops with 3 messages', () => {
    const messages = [
      makeMsg('user', 'Step 1', 0),
      makeMsg('user', 'continue', 10),
      makeMsg('user', 'continue again', 20),
    ];
    const loops = [
      createDefaultAgentLoop('L1'),
      createDefaultAgentLoop('L2'),
      createDefaultAgentLoop('L3'),
    ];

    const { pairedLoops } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops[0].userMessage).toBe('Step 1');
    expect(pairedLoops[1].userMessage).toBe('continue');
    expect(pairedLoops[2].userMessage).toBe('continue again');
  });

  it('preserves unpaired user messages when more messages than loops', () => {
    const messages = [
      makeMsg('user', 'Request 1', 0),
      makeMsg('user', 'Request 2', 5),
      makeMsg('user', 'Request 3', 10), // no loop for this
    ];
    const loops = [createDefaultAgentLoop('L1'), createDefaultAgentLoop('L2')];

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops).toHaveLength(2);
    expect(unpairedMessages).toHaveLength(1);
    expect(unpairedMessages[0].content).toBe('Request 3');
  });

  it('handles loops with no matching user messages', () => {
    const messages: PairableMessage[] = [];
    const loops = [createDefaultAgentLoop('L1')];

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops).toHaveLength(1);
    expect(pairedLoops[0].userMessage).toBeUndefined();
    expect(unpairedMessages).toHaveLength(0);
  });

  it('preserves non-user messages as unpaired', () => {
    const messages = [
      makeMsg('user', 'Request', 0),
      makeMsg('assistant', 'Some flat response', 3),
    ];
    const loops = [createDefaultAgentLoop('L1')];

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    expect(pairedLoops[0].userMessage).toBe('Request');
    expect(unpairedMessages).toHaveLength(1);
    expect(unpairedMessages[0].content).toBe('Some flat response');
    expect(unpairedMessages[0].role).toBe('assistant');
  });

  it('mixed session: user + assistant messages with loops', () => {
    const messages = [
      makeMsg('user', 'Hello', 0),
      makeMsg('assistant', 'Hi there', 1),
      makeMsg('user', 'Run RCA', 2),
      makeMsg('assistant', 'Starting...', 3),
    ];
    const loops = [createDefaultAgentLoop('L1')]; // only 1 loop

    const { pairedLoops, unpairedMessages } = pairMessagesWithLoops(messages, loops);

    // First user message paired with loop
    expect(pairedLoops[0].userMessage).toBe('Hello');
    // Remaining: 1 assistant + 1 user (unpaired) + 1 assistant
    expect(unpairedMessages).toHaveLength(3);
    // Sorted by order
    expect(unpairedMessages[0].content).toBe('Hi there');
    expect(unpairedMessages[1].content).toBe('Run RCA');
    expect(unpairedMessages[2].content).toBe('Starting...');
  });

  it('does not mutate original loop objects', () => {
    const loops = [createDefaultAgentLoop('L1')];
    const original = loops[0];

    pairMessagesWithLoops([makeMsg('user', 'Test', 0)], loops);

    expect(original.userMessage).toBeUndefined(); // original unchanged
  });
});
