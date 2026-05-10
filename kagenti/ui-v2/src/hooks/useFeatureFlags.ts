// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { useState, useEffect } from 'react';

export interface FeatureFlags {
  /** Sandboxed agent runtime UI and APIs (legacy runtime sandbox). */
  sandbox: boolean;
  integrations: boolean;
  triggers: boolean;
  /** agent-sandbox (kubernetes-sigs) as a fourth workload type. */
  agentSandbox: boolean;
  skills: boolean;
  /** AuthBridge statistics */
  authbridgeAPI: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  sandbox: false,
  integrations: false,
  triggers: false,
  agentSandbox: false,
  skills: false,
  authbridgeAPI: false,
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
          sandbox: data.sandbox === true,
          integrations: data.integrations === true,
          triggers: data.triggers === true,
          agentSandbox: data.agentSandbox === true,
          skills: data.skills === true,
          authbridgeAPI: data.authbridgeAPI === true,
          };
        cachedFlags = validated;
        setFlags(validated);
      })
      .catch((e) => { if (e?.name !== 'AbortError') console.debug('Feature flags fetch failed:', e); });
    return () => controller.abort();
  }, []);

  return flags;
}
