// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import type { GenerationStatus } from '@/services/api';

/**
 * Map a simulation generation status onto a Shipwright-style phase so the
 * shared getProgressInfo/getStatusIcon helpers can render it. Both Failed and
 * Error render as a Failed phase (the distinct reason is shown separately).
 */
export function mapGenerationStatusToPhase(
  status: GenerationStatus
): 'Running' | 'Succeeded' | 'Failed' {
  switch (status) {
    case 'Ready':
      return 'Succeeded';
    case 'Failed':
    case 'Error':
      return 'Failed';
    case 'Generating':
    default:
      return 'Running';
  }
}

/** True once generation has reached a terminal state and polling should stop. */
export function isGenerationTerminal(status: GenerationStatus): boolean {
  return status === 'Ready' || status === 'Failed' || status === 'Error';
}

/** True when raw Kubernetes labels carry the kagenti.io/simulated marker. */
export function isSimulatedLabels(
  labels: Record<string, string> | undefined | null
): boolean {
  return labels?.['kagenti.io/simulated'] === 'true';
}

/** Client-derived lifecycle state for a simulated tool. */
export type SimState = 'Stopped' | 'Generating' | 'Ready' | 'Failed' | 'Error';

/** Which detail-view actions are available for a given lifecycle state. */
export interface SimActions {
  start: boolean;
  stop: boolean;
  reset: boolean;
  seed: boolean;
  retry: boolean;
  delete: boolean;
}

/**
 * Derive a simulated tool's lifecycle state.
 *
 * The backend has no clean "Stopped" signal: a StatefulSet scaled to
 * replicas 0 reports readyStatus "Ready" (a 0>=0 fall-through) and
 * generation-status drifts to Failed/generation_stalled. The authoritative
 * Stopped signal is the desired replica count (spec.replicas === 0), which the
 * tool detail response passes through. When running (replicas > 0) we trust the
 * generation-status enum, defaulting to Generating while it is still loading.
 */
export function deriveSimState(args: {
  specReplicas: number | undefined;
  generationStatus: GenerationStatus | undefined;
}): SimState {
  if (args.specReplicas === 0) return 'Stopped';
  return args.generationStatus ?? 'Generating';
}

/** The action matrix: which dropdown items render for a given state. */
export function availableSimActions(state: SimState): SimActions {
  const none: SimActions = {
    start: false, stop: false, reset: false, seed: false, retry: false, delete: true,
  };
  switch (state) {
    case 'Ready':
      return { ...none, stop: true, reset: true, seed: true };
    case 'Stopped':
      return { ...none, start: true };
    case 'Error':
      return { ...none, retry: true };
    case 'Generating':
    case 'Failed':
    default:
      return none;
  }
}

/** Header badge color for a lifecycle state. */
export function simStateBadgeColor(state: SimState): 'green' | 'grey' | 'blue' | 'red' {
  switch (state) {
    case 'Ready':
      return 'green';
    case 'Stopped':
      return 'grey';
    case 'Generating':
      return 'blue';
    case 'Failed':
    case 'Error':
    default:
      return 'red';
  }
}
