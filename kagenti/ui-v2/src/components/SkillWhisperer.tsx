// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useCallback, useRef } from 'react';

export interface SkillItem {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
}

interface SkillWhispererProps {
  skills: SkillItem[];
  input: string;
  onSelect: (skillId: string) => void;
  onDismiss: () => void;
}

/**
 * Floating dropdown that shows agent skills when the user types "/".
 * Positioned above the chat textarea. Filters skills as the user types.
 *
 * Keyboard: ArrowUp/Down to navigate, Enter to select, Escape to dismiss.
 */
export const SkillWhisperer: React.FC<SkillWhispererProps> = ({
  skills,
  input,
  onSelect,
  onDismiss,
}) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  // Extract the slash-command query from input
  const slashMatch = input.match(/(?:^|\s)\/([\w:.-]*)$/);
  const query = slashMatch ? slashMatch[1].toLowerCase() : null;

  // Filter skills by query
  const filtered = query !== null
    ? skills.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.name.toLowerCase().includes(query)
      )
    : [];

  const isOpen = query !== null && filtered.length > 0;

  // Reset selection when filtered list changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && filtered.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        onSelect(filtered[selectedIndex].id);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onDismiss();
      } else if (e.key === 'Tab') {
        if (filtered.length > 0) {
          e.preventDefault();
          onSelect(filtered[selectedIndex].id);
        }
      }
    },
    [isOpen, filtered, selectedIndex, onSelect, onDismiss]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown, true);
      return () => document.removeEventListener('keydown', handleKeyDown, true);
    }
  }, [isOpen, handleKeyDown]);

  // Scroll selected item into view
  useEffect(() => {
    if (!menuRef.current) return;
    const items = menuRef.current.querySelectorAll('[data-skill-item]');
    items[selectedIndex]?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (!isOpen) return null;

  return (
    <div
      ref={menuRef}
      data-testid="skill-whisperer"
      style={{
        position: 'absolute',
        bottom: '100%',
        left: 0,
        right: 0,
        marginBottom: 4,
        background: 'var(--pf-v5-global--BackgroundColor--100)',
        border: '1px solid var(--pf-v5-global--BorderColor--100)',
        borderRadius: 6,
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        maxHeight: 240,
        overflowY: 'auto',
        zIndex: 1000,
      }}
    >
      <div style={{ padding: '4px 8px', fontSize: 11, color: 'var(--pf-v5-global--Color--200)' }}>
        Skills ({filtered.length})
      </div>
      {filtered.map((skill, i) => (
        <div
          key={skill.id}
          data-skill-item
          data-testid={`skill-option-${skill.id}`}
          onClick={() => onSelect(skill.id)}
          onMouseEnter={() => setSelectedIndex(i)}
          style={{
            padding: '8px 12px',
            cursor: 'pointer',
            background:
              i === selectedIndex
                ? 'var(--pf-v5-global--BackgroundColor--200)'
                : 'transparent',
          }}
        >
          <div style={{ fontWeight: 600, fontFamily: 'var(--pf-v5-global--FontFamily--monospace)' }}>
            /{skill.id}
          </div>
          {skill.description && (
            <div
              style={{
                fontSize: 12,
                color: 'var(--pf-v5-global--Color--200)',
                marginTop: 2,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {skill.description}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};
