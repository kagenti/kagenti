// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Copy text to clipboard with fallback for non-secure contexts.
 *
 * The native Clipboard API (navigator.clipboard) requires a secure context
 * (HTTPS or localhost). When the UI is served over plain HTTP through an
 * ingress gateway, the API is unavailable. This helper falls back to the
 * legacy document.execCommand('copy') approach in that case.
 */
export function copyToClipboard(
  _event: React.ClipboardEvent<HTMLDivElement>,
  text?: React.ReactNode
): void {
  const value = typeof text === 'string' ? text : String(text ?? '');

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(value);
    return;
  }

  // Fallback: create a temporary textarea, select its content, and copy
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '-9999px';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    document.execCommand('copy');
  } finally {
    document.body.removeChild(textarea);
  }
}
