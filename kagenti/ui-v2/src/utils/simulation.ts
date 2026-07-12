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
