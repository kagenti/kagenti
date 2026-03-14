// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * ModelBadge — small inline colored badge showing the LLM model name.
 *
 * Maps known model identifiers to friendly labels and colors.
 * Unknown models render with a gray badge and truncated name.
 */

import React from 'react';

interface ModelBadgeProps {
  model: string;
}

interface ModelInfo {
  label: string;
  bg: string;
  color: string;
}

const MODEL_MAP: Record<string, ModelInfo> = {
  'llama-4-scout':  { label: 'Llama 4',  bg: '#0066cc', color: '#fff' },
  'mistral-small':  { label: 'Mistral',  bg: '#7b2d8e', color: '#fff' },
  'gpt-4o':         { label: 'GPT-4o',   bg: '#10a37f', color: '#fff' },
  'claude-sonnet':  { label: 'Claude',   bg: '#d97706', color: '#fff' },
};

function resolveModel(model: string): ModelInfo {
  // Exact match first
  if (MODEL_MAP[model]) return MODEL_MAP[model];

  // Partial match — check if model string contains a known key
  for (const [key, info] of Object.entries(MODEL_MAP)) {
    if (model.toLowerCase().includes(key)) return info;
  }

  // Default: gray badge with truncated name
  const label = model.length > 16 ? model.slice(0, 14) + '\u2026' : model;
  return { label, bg: '#6a6e73', color: '#fff' };
}

export const ModelBadge: React.FC<ModelBadgeProps> = ({ model }) => {
  const info = resolveModel(model);

  return (
    <span
      title={`LLM model: ${model}`}
      style={{
        display: 'inline-block',
        padding: '1px 8px',
        borderRadius: 10,
        fontSize: '0.78em',
        fontWeight: 600,
        lineHeight: '18px',
        backgroundColor: info.bg,
        color: info.color,
        whiteSpace: 'nowrap',
      }}
    >
      {info.label}
    </span>
  );
};
