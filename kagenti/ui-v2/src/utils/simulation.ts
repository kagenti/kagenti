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

/** Result of parsing a user-supplied db.json seed. */
export type SeedParseResult =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; error: string };

/**
 * Validate that a seed string is a JSON object (mirrors the backend's
 * synchronous 422 for malformed / non-object bodies). Schema validation is the
 * harness's job; this only gates syntactic validity.
 */
export function parseSeedDatabase(text: string): SeedParseResult {
  if (!text.trim()) {
    return { ok: false, error: 'Enter a db.json document (a JSON object).' };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: 'Dataset is not valid JSON.' };
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'Dataset must be a JSON object.' };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

/**
 * Map a reseed failure (an ApiError-shaped value) to a user-facing message,
 * surfacing the harness `json_path` on a 422. Duck-types the error so the helper
 * stays import-free and unit-testable.
 */
export function extractReseedError(err: unknown): { message: string; jsonPath?: string } {
  const e = err as { status?: number; message?: string; detail?: unknown } | null;
  if (!e || typeof e !== 'object' || typeof e.status !== 'number') {
    return { message: 'Unexpected error re-seeding the database.' };
  }
  switch (e.status) {
    case 422: {
      const detail = e.detail;
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const d = detail as { message?: string; json_path?: string };
        return {
          message: d.message || 'Dataset does not validate against the tool schema',
          jsonPath: d.json_path,
        };
      }
      return { message: e.message || 'Dataset does not validate against the tool schema' };
    }
    case 409:
      return { message: 'Tool calls are in flight — retry the re-seed shortly.' };
    case 502:
      return { message: 'Simulated tool is not reachable (it may be stopped).' };
    default:
      return { message: e.message || 'Failed to re-seed the database.' };
  }
}
