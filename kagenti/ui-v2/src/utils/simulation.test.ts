// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import {
  mapGenerationStatusToPhase,
  isGenerationTerminal,
  isSimulatedLabels,
  deriveSimState,
  availableSimActions,
  simStateBadgeColor,
  parseSeedDatabase,
  extractReseedError,
} from './simulation';

describe('mapGenerationStatusToPhase', () => {
  it('maps Ready to Succeeded', () => {
    expect(mapGenerationStatusToPhase('Ready')).toBe('Succeeded');
  });
  it('maps Failed to Failed', () => {
    expect(mapGenerationStatusToPhase('Failed')).toBe('Failed');
  });
  it('maps Error to Failed', () => {
    expect(mapGenerationStatusToPhase('Error')).toBe('Failed');
  });
  it('maps Generating to Running', () => {
    expect(mapGenerationStatusToPhase('Generating')).toBe('Running');
  });
});

describe('isGenerationTerminal', () => {
  it('is true for Ready, Failed, and Error', () => {
    expect(isGenerationTerminal('Ready')).toBe(true);
    expect(isGenerationTerminal('Failed')).toBe(true);
    expect(isGenerationTerminal('Error')).toBe(true);
  });
  it('is false for Generating', () => {
    expect(isGenerationTerminal('Generating')).toBe(false);
  });
});

describe('isSimulatedLabels', () => {
  it('is true when the marker equals "true"', () => {
    expect(isSimulatedLabels({ 'kagenti.io/simulated': 'true' })).toBe(true);
  });
  it('is false when the marker is absent', () => {
    expect(isSimulatedLabels({ 'kagenti.io/framework': 'python' })).toBe(false);
  });
  it('is false when the marker is not "true"', () => {
    expect(isSimulatedLabels({ 'kagenti.io/simulated': 'false' })).toBe(false);
  });
  it('is false for undefined/null', () => {
    expect(isSimulatedLabels(undefined)).toBe(false);
    expect(isSimulatedLabels(null)).toBe(false);
  });
});

describe('deriveSimState', () => {
  it('is Stopped when specReplicas is 0, regardless of generation status', () => {
    expect(deriveSimState({ specReplicas: 0, generationStatus: 'Ready' })).toBe('Stopped');
    expect(deriveSimState({ specReplicas: 0, generationStatus: 'Failed' })).toBe('Stopped');
    expect(deriveSimState({ specReplicas: 0, generationStatus: undefined })).toBe('Stopped');
  });
  it('passes through the generation status when replicas > 0', () => {
    expect(deriveSimState({ specReplicas: 1, generationStatus: 'Ready' })).toBe('Ready');
    expect(deriveSimState({ specReplicas: 1, generationStatus: 'Generating' })).toBe('Generating');
    expect(deriveSimState({ specReplicas: 1, generationStatus: 'Failed' })).toBe('Failed');
    expect(deriveSimState({ specReplicas: 1, generationStatus: 'Error' })).toBe('Error');
  });
  it('defaults to Generating when replicas > 0 but status is not yet known', () => {
    expect(deriveSimState({ specReplicas: 1, generationStatus: undefined })).toBe('Generating');
  });
  it('treats undefined replicas (tool not yet loaded) as not-stopped', () => {
    expect(deriveSimState({ specReplicas: undefined, generationStatus: 'Ready' })).toBe('Ready');
  });
});

describe('availableSimActions', () => {
  it('Ready allows stop, reset, seed, delete (not start/retry)', () => {
    expect(availableSimActions('Ready')).toEqual({
      start: false, stop: true, reset: true, seed: true, retry: false, delete: true,
    });
  });
  it('Stopped allows start and delete only', () => {
    expect(availableSimActions('Stopped')).toEqual({
      start: true, stop: false, reset: false, seed: false, retry: false, delete: true,
    });
  });
  it('Generating allows delete only', () => {
    expect(availableSimActions('Generating')).toEqual({
      start: false, stop: false, reset: false, seed: false, retry: false, delete: true,
    });
  });
  it('Error allows retry and delete', () => {
    expect(availableSimActions('Error')).toEqual({
      start: false, stop: false, reset: false, seed: false, retry: true, delete: true,
    });
  });
  it('Failed allows delete only', () => {
    expect(availableSimActions('Failed')).toEqual({
      start: false, stop: false, reset: false, seed: false, retry: false, delete: true,
    });
  });
});

describe('simStateBadgeColor', () => {
  it('maps each state to its color', () => {
    expect(simStateBadgeColor('Ready')).toBe('green');
    expect(simStateBadgeColor('Stopped')).toBe('grey');
    expect(simStateBadgeColor('Generating')).toBe('blue');
    expect(simStateBadgeColor('Failed')).toBe('red');
    expect(simStateBadgeColor('Error')).toBe('red');
  });
});

describe('parseSeedDatabase', () => {
  it('accepts a JSON object', () => {
    expect(parseSeedDatabase('{"users": []}')).toEqual({ ok: true, value: { users: [] } });
  });
  it('rejects malformed JSON', () => {
    const r = parseSeedDatabase('not json');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/valid JSON/i);
  });
  it('rejects a JSON array', () => {
    const r = parseSeedDatabase('[]');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/object/i);
  });
  it('rejects a JSON scalar', () => {
    expect(parseSeedDatabase('42').ok).toBe(false);
    expect(parseSeedDatabase('"x"').ok).toBe(false);
    expect(parseSeedDatabase('null').ok).toBe(false);
  });
  it('rejects empty/whitespace input', () => {
    expect(parseSeedDatabase('   ').ok).toBe(false);
  });
});

describe('extractReseedError', () => {
  it('pulls json_path and message from a 422 object detail', () => {
    const err = { status: 422, message: 'x', detail: { message: 'bad row', json_path: '$.users[0].id' } };
    expect(extractReseedError(err)).toEqual({ message: 'bad row', jsonPath: '$.users[0].id' });
  });
  it('falls back to a schema message when the 422 object has no message', () => {
    const err = { status: 422, message: 'x', detail: { json_path: '$.a' } };
    expect(extractReseedError(err)).toEqual({
      message: 'Dataset does not validate against the tool schema',
      jsonPath: '$.a',
    });
  });
  it('uses the error message for a 422 string detail (pre-flight malformed JSON)', () => {
    const err = { status: 422, message: 'database is not valid JSON', detail: 'database is not valid JSON' };
    expect(extractReseedError(err)).toEqual({ message: 'database is not valid JSON' });
  });
  it('maps 409 to an in-flight message', () => {
    expect(extractReseedError({ status: 409, message: 'x' })).toEqual({
      message: 'Tool calls are in flight — retry the re-seed shortly.',
    });
  });
  it('maps 502 to an unreachable message', () => {
    expect(extractReseedError({ status: 502, message: 'x' })).toEqual({
      message: 'Simulated tool is not reachable (it may be stopped).',
    });
  });
  it('falls back to the error message for other statuses', () => {
    expect(extractReseedError({ status: 500, message: 'boom' })).toEqual({ message: 'boom' });
  });
  it('handles a non-ApiError value', () => {
    expect(extractReseedError('weird')).toEqual({ message: 'Unexpected error re-seeding the database.' });
  });
});
