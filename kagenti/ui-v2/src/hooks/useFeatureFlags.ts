// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { useState, useEffect } from 'react';
import { API_CONFIG } from '@/services/api';

export interface FeatureFlags {
  sandbox: boolean;
  integrations: boolean;
  triggers: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  sandbox: false,
  integrations: false,
  triggers: false,
};

let cachedFlags: FeatureFlags | null = null;

export function useFeatureFlags(): FeatureFlags {
  const [flags, setFlags] = useState<FeatureFlags>(cachedFlags ?? DEFAULT_FLAGS);

  useEffect(() => {
    if (cachedFlags) return;
    fetch(`${API_CONFIG.baseUrl}/config/features`)
      .then(res => res.json())
      .then((data: FeatureFlags) => {
        cachedFlags = data;
        setFlags(data);
      })
      .catch(() => setFlags(DEFAULT_FLAGS));
  }, []);

  return flags;
}
