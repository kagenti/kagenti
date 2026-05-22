// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { useQuery } from '@tanstack/react-query';
import { namespaceService } from '@/services/api';

/**
 * Hook to fetch available Kubernetes namespaces.
 *
 * @param enabledOnly - If true, only returns namespaces with kagenti-enabled=true label
 * @returns Query result with namespaces array
 */
export function useNamespaces(enabledOnly: boolean = true) {
  return useQuery({
    queryKey: ['namespaces', enabledOnly],
    queryFn: () => namespaceService.list(enabledOnly),
    staleTime: 60000, // Cache for 1 minute
    retry: 2,
  });
}
