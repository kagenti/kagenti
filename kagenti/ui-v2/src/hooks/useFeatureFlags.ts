// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts';

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

export function useFeatureFlags(): FeatureFlags & { isLoadingFlags: boolean } {
  const { isLoading: isAuthLoading } = useAuth();
  const [flags, setFlags] = useState<FeatureFlags>(cachedFlags ?? DEFAULT_FLAGS);
  const [isLoadingFlags, setIsLoadingFlags] = useState(!cachedFlags);

  useEffect(() => {
    if (cachedFlags) {
      setIsLoadingFlags(false);
      return;
    }
    if (isAuthLoading) return;
    const controller = new AbortController();
    fetch('/api/v1/config/features', {
      signal: controller.signal,
    })
      .then(res => res.ok ? res.json() : DEFAULT_FLAGS)
      .then((data) => {
        const validated: FeatureFlags = {
          sandbox: data.sandbox === true,
          integrations: data.integrations === true,
          triggers: data.triggers === true,
        };
        cachedFlags = validated;
        setFlags(validated);
        setIsLoadingFlags(false);
      })
      .catch((e) => {
        if (e?.name !== 'AbortError') {
          console.debug('Feature flags fetch failed:', e);
          setIsLoadingFlags(false);
        }
      });
    return () => controller.abort();
  }, [isAuthLoading]);

  return { ...flags, isLoadingFlags };
}
