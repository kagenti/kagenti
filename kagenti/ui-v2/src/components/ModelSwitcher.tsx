// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * ModelSwitcher — Popover triggered by clicking the model badge/cog in the
 * session header. Lets users dynamically switch LLM models per session.
 */

import React, { useState, useEffect } from 'react';
import {
  Popover,
  Button,
  Label,
  Tooltip,
  MenuToggle,
  Select,
  SelectOption,
  SelectList,
  Spinner,
} from '@patternfly/react-core';
import { CogIcon, SyncAltIcon } from '@patternfly/react-icons';
import { modelsService } from '../services/api';

export interface ModelSwitcherProps {
  currentModel: string;
  onModelChange: (model: string) => void;
  namespace: string;
  agentName?: string;
}

export const ModelSwitcher: React.FC<ModelSwitcherProps> = ({
  currentModel,
  onModelChange,
  namespace,
  agentName,
}) => {
  const [models, setModels] = useState<Array<{ id: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectOpen, setSelectOpen] = useState(false);

  const fetchModels = async () => {
    setLoading(true);
    setError(null);
    try {
      // Use agent-specific models if agent name is known, else all models
      const result = agentName && namespace
        ? await modelsService.getAgentModels(namespace, agentName)
        : await modelsService.getAvailableModels();
      setModels(result);
    } catch (err) {
      // Fallback to all models if agent-specific fails
      try {
        const fallback = await modelsService.getAvailableModels();
        setModels(fallback);
      } catch {
        setError('Failed to load models');
        console.warn('ModelSwitcher: failed to fetch models', err);
      }
    } finally {
      setLoading(false);
    }
  };

  // Fetch models when popover opens (triggered by shouldOpen/shouldClose)
  const [popoverVisible, setPopoverVisible] = useState(false);
  useEffect(() => {
    if (popoverVisible) {
      fetchModels();
    }
  }, [popoverVisible]);

  const displayModel = currentModel || 'llama4-scout';

  const popoverBody = (
    <div style={{ minWidth: 260 }}>
      <div style={{ marginBottom: 12, fontWeight: 600, fontSize: '0.9em' }}>
        Switch LLM Model
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 16 }}>
          <Spinner size="md" />
        </div>
      )}

      {error && (
        <div style={{ color: 'var(--pf-v5-global--danger-color--100)', marginBottom: 8, fontSize: '0.85em' }}>
          {error}
        </div>
      )}

      {!loading && (
        <Select
          isOpen={selectOpen}
          selected={displayModel}
          onSelect={(_event, value) => {
            if (typeof value === 'string') {
              onModelChange(value);
            }
            setSelectOpen(false);
          }}
          onOpenChange={(isOpen) => setSelectOpen(isOpen)}
          toggle={(toggleRef) => (
            <MenuToggle
              ref={toggleRef}
              onClick={() => setSelectOpen(!selectOpen)}
              isExpanded={selectOpen}
              style={{ width: '100%' }}
            >
              {displayModel}
            </MenuToggle>
          )}
          shouldFocusToggleOnSelect
        >
          <SelectList>
            {models.length === 0 && !error ? (
              <SelectOption key="__none" value="" isDisabled>
                No models available
              </SelectOption>
            ) : (
              models.map((m) => (
                <SelectOption key={m.id} value={m.id}>
                  {m.id}
                </SelectOption>
              ))
            )}
          </SelectList>
        </Select>
      )}

      <div style={{ marginTop: 16 }}>
        <Tooltip content="Coming soon">
          <Button
            variant="secondary"
            icon={<SyncAltIcon />}
            isDisabled
            isBlock
            size="sm"
          >
            Rebuild Agent
          </Button>
        </Tooltip>
      </div>
    </div>
  );

  return (
    <Popover
      aria-label="Model switcher"
      headerContent="Model Configuration"
      bodyContent={popoverBody}
      position="bottom"
      shouldOpen={() => setPopoverVisible(true)}
      shouldClose={() => {
        setPopoverVisible(false);
        setSelectOpen(false);
      }}
    >
      <span style={{ cursor: 'pointer' }}>
        <Label isCompact color="orange" icon={<CogIcon />}>
          {displayModel}
        </Label>
      </span>
    </Popover>
  );
};
