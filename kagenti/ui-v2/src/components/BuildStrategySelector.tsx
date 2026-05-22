// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect } from 'react';
import {
  Select,
  SelectOption,
  SelectList,
  MenuToggle,
  MenuToggleElement,
  FormHelperText,
  HelperText,
  HelperTextItem,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';

import { shipwrightService, ClusterBuildStrategy } from '@/services/api';

// Default strategies with descriptions
const DEFAULT_STRATEGY_DESCRIPTIONS: Record<string, string> = {
  'buildah-insecure-push': 'For internal registries without TLS (dev/kind clusters)',
  'buildah': 'For external registries with TLS (quay.io, ghcr.io, docker.io)',
};

interface BuildStrategySelectorProps {
  value: string;
  onChange: (strategy: string) => void;
  registryType: string;
  disabled?: boolean;
  minWidth?: string;
}

/**
 * Component to select a ClusterBuildStrategy for Shipwright builds.
 * Auto-selects appropriate strategy based on registry type.
 */
export const BuildStrategySelector: React.FC<BuildStrategySelectorProps> = ({
  value,
  onChange,
  registryType,
  disabled = false,
  minWidth = '250px',
}) => {
  const [isOpen, setIsOpen] = useState(false);

  // Fetch available strategies from the backend
  const {
    data: strategies = [],
    isLoading,
    error,
  } = useQuery<ClusterBuildStrategy[]>({
    queryKey: ['buildStrategies'],
    queryFn: () => shipwrightService.listBuildStrategies(),
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  // Auto-select strategy based on registry type
  useEffect(() => {
    if (strategies.length === 0) return;

    // Determine the appropriate strategy based on registry
    const isInternalRegistry = registryType === 'local';
    const recommendedStrategy = isInternalRegistry ? 'buildah-insecure-push' : 'buildah';

    // Check if recommended strategy is available
    const hasRecommended = strategies.some((s) => s.name === recommendedStrategy);

    // Only auto-select if current value is empty or doesn't exist in available strategies
    const currentExists = strategies.some((s) => s.name === value);
    if (!value || !currentExists) {
      if (hasRecommended) {
        onChange(recommendedStrategy);
      } else if (strategies.length > 0) {
        onChange(strategies[0].name);
      }
    }
  }, [registryType, strategies, value, onChange]);

  const onSelect = (
    _event: React.MouseEvent | undefined,
    selectedValue: string | number | undefined
  ) => {
    if (selectedValue) {
      onChange(selectedValue as string);
    }
    setIsOpen(false);
  };

  // Get description for current strategy
  const getDescription = (strategyName: string): string | undefined => {
    const strategy = strategies.find((s) => s.name === strategyName);
    return strategy?.description || DEFAULT_STRATEGY_DESCRIPTIONS[strategyName];
  };

  const currentDescription = getDescription(value);

  if (error) {
    return (
      <FormHelperText>
        <HelperText>
          <HelperTextItem variant="error">
            Failed to load build strategies. Using default.
          </HelperTextItem>
        </HelperText>
      </FormHelperText>
    );
  }

  return (
    <>
      <Select
        aria-label="Select build strategy"
        isOpen={isOpen}
        selected={value}
        onSelect={onSelect}
        onOpenChange={(open) => setIsOpen(open)}
        toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
          <MenuToggle
            ref={toggleRef}
            onClick={() => setIsOpen(!isOpen)}
            isExpanded={isOpen}
            isDisabled={disabled || isLoading}
            style={{ minWidth }}
          >
            {isLoading ? 'Loading strategies...' : value || 'Select build strategy'}
          </MenuToggle>
        )}
      >
        <SelectList>
          {strategies.map((strategy) => (
            <SelectOption
              key={strategy.name}
              value={strategy.name}
              description={strategy.description || DEFAULT_STRATEGY_DESCRIPTIONS[strategy.name]}
            >
              {strategy.name}
            </SelectOption>
          ))}
        </SelectList>
      </Select>
      {currentDescription && (
        <FormHelperText>
          <HelperText>
            <HelperTextItem>{currentDescription}</HelperTextItem>
          </HelperText>
        </FormHelperText>
      )}
    </>
  );
};
