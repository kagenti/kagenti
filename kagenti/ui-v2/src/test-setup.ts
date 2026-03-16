// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Vitest setup file — register a require hook that short-circuits
 * CSS file imports so PatternFly and xyflow styles don't crash
 * in the Node.js test environment.
 */

export {}; // Make this file a module (required for top-level await)

// Intercept .css requires at the Module level
const Module = await import('module');
const _origLoad = (Module as any).default._load;

(Module as any).default._load = function (request: string, parent: any, isMain: boolean) {
  if (request.endsWith('.css')) {
    return {};
  }
  return _origLoad.call(this, request, parent, isMain);
};
