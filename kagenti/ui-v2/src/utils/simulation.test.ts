// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import {
  mapGenerationStatusToPhase,
  isGenerationTerminal,
  isSimulatedLabels,
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
