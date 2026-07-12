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
