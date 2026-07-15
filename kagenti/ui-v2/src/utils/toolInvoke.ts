// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Seed the invoke form's arg map. Only keys with an explicit schema `default`
 * are pre-filled — no sentinel (0 / '' / false) fabrication, so untouched
 * optional fields stay absent and are omitted at submit time.
 */
export const initialInvokeArgs = (
  properties?: Record<string, { default?: unknown }>,
): Record<string, unknown> => {
  const args: Record<string, unknown> = {};
  if (!properties) return args;
  for (const [key, prop] of Object.entries(properties)) {
    if (prop && prop.default !== undefined) {
      args[key] = prop.default;
    }
  }
  return args;
};

/**
 * Build the payload sent to the tool. A key is included when it is required,
 * or when the user actually set a value (anything that is not `undefined` and
 * not an empty string). Explicit 0 / false are preserved.
 */
export const buildInvokeArgs = (
  toolArgs: Record<string, unknown>,
  required: string[],
): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(toolArgs).filter(
      ([k, v]) => required.includes(k) || (v !== undefined && v !== ''),
    ),
  );
