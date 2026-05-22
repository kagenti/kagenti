// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Validate environment variable name according to Kubernetes rules.
 *
 * Must start with a letter or underscore, followed by any combination
 * of letters, digits, or underscores.
 */
export const isValidEnvVarName = (name: string): boolean => {
  if (!name) return false;
  const pattern = /^[A-Za-z_][A-Za-z0-9_]*$/;
  return pattern.test(name);
};

/**
 * Validate container image path.
 *
 * Requires at least two slash-separated segments (NAMESPACE/REPOSITORY).
 * The first segment may be a HOST[:PORT] prefix (detected by the
 * presence of a "." or ":").  Additional path segments are allowed
 * (e.g., ghcr.io/org/repo/subpath).
 */
export const isValidContainerImage = (image: string): boolean => {
  const parts = image.split('/');
  if (parts.length < 2) return false;
  if (parts.some((p) => p.length === 0)) return false;

  const validSegment = /^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$/;
  const validHost = /^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?(:[0-9]+)?$/;

  // If the first segment contains a "." or ":" treat it as HOST[:PORT]
  const firstIsHost = /[.:]/.test(parts[0]);

  if (firstIsHost) {
    if (!validHost.test(parts[0])) return false;
  } else {
    if (!validSegment.test(parts[0])) return false;
  }

  return parts.slice(1).every((p) => validSegment.test(p));
};

/**
 * Validate an image tag.
 *
 * Must be valid ASCII containing only letters, digits, underscores,
 * periods, and dashes. May not start with a period or a dash.
 */
export const isValidImageTag = (tag: string): boolean => {
  if (!tag) return false;
  return /^[a-zA-Z0-9_][a-zA-Z0-9._-]*$/.test(tag);
};
