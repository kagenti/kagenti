// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

export function workloadTypeColor(type: string): 'grey' | 'orange' | 'gold' | 'purple' {
  switch (type) {
    case 'sandbox': return 'purple';
    case 'job': return 'orange';
    case 'statefulset': return 'gold';
    default: return 'grey';
  }
}

export const WORKLOAD_META: Record<string, { apiVersion: string; kind: string }> = {
  sandbox: { apiVersion: 'agents.x-k8s.io/v1alpha1', kind: 'Sandbox' },
  statefulset: { apiVersion: 'apps/v1', kind: 'StatefulSet' },
  job: { apiVersion: 'batch/v1', kind: 'Job' },
  deployment: { apiVersion: 'apps/v1', kind: 'Deployment' },
};
