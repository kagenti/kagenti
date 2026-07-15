// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { useState, useEffect } from 'react';

export interface FeatureFlags {
  /** Shipwright build-from-source capability available in the cluster. */
  builds: boolean;
  /** Sandboxed agent runtime UI and APIs (legacy runtime sandbox). */
  sandbox: boolean;
  integrations: boolean;
  triggers: boolean;
  /** agent-sandbox (kubernetes-sigs) as a fourth workload type. */
  agentSandbox: boolean;
  skills: boolean;
  /** AuthBridge statistics */
  authbridgeAPI: boolean;
  /** Platform Status card and /platform-status endpoint */
  admin: boolean;
  /** External skill registry references */
  externalSkills: boolean;
  /** Trace-analysis Observability card */
  traceAnalysis: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  builds: false,
  sandbox: false,
  integrations: false,
  triggers: false,
  agentSandbox: false,
  skills: false,
  authbridgeAPI: false,
  admin: false,
  externalSkills: false,
  traceAnalysis: false,
};

let cachedFlags: FeatureFlags | null = null;

export function useFeatureFlags(): FeatureFlags {
  const [flags, setFlags] = useState<FeatureFlags>(cachedFlags ?? DEFAULT_FLAGS);

  useEffect(() => {
    if (cachedFlags) return;
    const controller = new AbortController();
    fetch('/api/v1/config/features', { signal: controller.signal })
      .then(res => res.ok ? res.json() : DEFAULT_FLAGS)
      .then((data) => {
        const validated: FeatureFlags = {
          builds: data.builds === true,
          sandbox: data.sandbox === true,
          integrations: data.integrations === true,
          triggers: data.triggers === true,
          agentSandbox: data.agentSandbox === true,
          skills: data.skills === true,
          authbridgeAPI: data.authbridgeAPI === true,
          admin: data.admin === true,
          externalSkills: data.externalSkills === true,
          traceAnalysis: data.traceAnalysis === true,
          };
        cachedFlags = validated;
        setFlags(validated);
      })
      .catch((e) => { if (e?.name !== 'AbortError') console.debug('Feature flags fetch failed:', e); });
    return () => controller.abort();
  }, []);

  return flags;
}
