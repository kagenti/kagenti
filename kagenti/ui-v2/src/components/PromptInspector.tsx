// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';

interface PromptInspectorProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  systemPrompt?: string;
  promptMessages?: Array<{ role: string; preview: string }>;
  boundTools?: Array<{ name: string; description?: string }>;
  response?: string;
  model?: string;
  promptTokens?: number;
  completionTokens?: number;
}

const PromptInspector: React.FC<PromptInspectorProps> = ({
  isOpen, onClose, title, systemPrompt, promptMessages, boundTools,
  response, model, promptTokens, completionTokens,
}) => {
  // Close on ESC key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Use portal to render at document.body level — escapes any parent
  // stacking context (transform, filter, will-change) that would make
  // position:fixed relative to the parent instead of the viewport.
  return createPortal(
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.8)', zIndex: 9999,
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px 24px', borderBottom: '1px solid #333',
        backgroundColor: '#1a1a2e', color: '#fff',
      }}>
        <h2 style={{ margin: 0, fontSize: '18px' }}>{title}</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {model && <span style={{ fontSize: '12px', color: '#888' }}>Model: {model}</span>}
          {(promptTokens || completionTokens) && (
            <span style={{ fontSize: '12px', color: '#888' }}>
              Tokens: {promptTokens ?? 0} in / {completionTokens ?? 0} out
            </span>
          )}
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: '#fff',
              fontSize: '24px', cursor: 'pointer', padding: '4px',
            }}
            aria-label="Close prompt inspector"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{
        flex: 1, overflow: 'auto', padding: '24px',
        backgroundColor: '#0d1117', color: '#e6edf3',
      }}>
        {/* System Prompt */}
        {systemPrompt && (
          <section style={{ marginBottom: '24px' }}>
            <h3 style={{ color: '#58a6ff', fontSize: '14px', marginBottom: '8px' }}>
              System Prompt
            </h3>
            <pre style={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              backgroundColor: '#161b22', padding: '16px', borderRadius: '6px',
              fontSize: '13px', lineHeight: '1.5', maxHeight: '400px', overflow: 'auto',
              border: '1px solid #30363d',
            }}>
              {systemPrompt}
            </pre>
          </section>
        )}

        {/* Bound Tools */}
        <section style={{ marginBottom: '24px' }}>
          <h3 style={{ color: '#58a6ff', fontSize: '14px', marginBottom: '8px' }}>
            Bound Tools ({boundTools?.length ?? 0})
          </h3>
          {boundTools && boundTools.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {boundTools.map((t, i) => (
                <span key={i} title={t.description || t.name} style={{
                  display: 'inline-block', padding: '3px 8px', borderRadius: '4px',
                  fontSize: '12px', fontWeight: 500,
                  backgroundColor: '#1f6feb22', color: '#58a6ff',
                  border: '1px solid #1f6feb44',
                }}>
                  {t.name}
                </span>
              ))}
            </div>
          ) : (
            <span style={{ fontSize: '12px', color: '#484f58' }}>No tools bound (text-only node)</span>
          )}
        </section>

        {/* Input Messages */}
        {promptMessages && promptMessages.length > 0 && (
          <section style={{ marginBottom: '24px' }}>
            <h3 style={{ color: '#58a6ff', fontSize: '14px', marginBottom: '8px' }}>
              Input Messages ({promptMessages.length})
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {promptMessages.map((msg, i) => (
                <div key={i} style={{
                  backgroundColor: '#161b22', padding: '12px 16px',
                  borderRadius: '6px', border: '1px solid #30363d',
                }}>
                  <span style={{
                    fontSize: '11px', fontWeight: 'bold',
                    color: msg.role === 'user' ? '#3fb950' : msg.role === 'assistant' ? '#58a6ff' : '#d29922',
                    textTransform: 'uppercase',
                  }}>
                    {msg.role}
                  </span>
                  <pre style={{
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    fontSize: '13px', lineHeight: '1.5', marginTop: '4px',
                    margin: 0,
                  }}>
                    {msg.preview}
                  </pre>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* LLM Response */}
        {response && (
          <section style={{ marginBottom: '24px' }}>
            <h3 style={{ color: '#58a6ff', fontSize: '14px', marginBottom: '8px' }}>
              LLM Response
            </h3>
            <pre style={{
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              backgroundColor: '#161b22', padding: '16px', borderRadius: '6px',
              fontSize: '13px', lineHeight: '1.5', maxHeight: '600px', overflow: 'auto',
              border: '1px solid #30363d',
            }}>
              {response}
            </pre>
          </section>
        )}
      </div>
    </div>,
    document.body,
  );
};

export default PromptInspector;
