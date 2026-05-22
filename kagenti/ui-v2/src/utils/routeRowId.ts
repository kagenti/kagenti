// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Unique id for outbound route row keys (React `key` prop).
 *
 * Avoid calling `crypto.randomUUID()` directly: on http:// hosts such as
 * kagenti-ui.localtest.me it may be missing or throw; some browsers expose
 * `crypto` without `randomUUID`.
 */
export function newRouteRowId(): string {
  try {
    const c = globalThis.crypto;
    if (c != null && typeof c.randomUUID === 'function') {
      return c.randomUUID();
    }
  } catch {
    /* Secure-context or implementation errors */
  }
  return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 11)}`;
}
