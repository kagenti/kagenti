// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import {
  Select,
  SelectOption,
  SelectList,
  MenuToggle,
  MenuToggleElement,
} from '@patternfly/react-core';

import { useNamespaces } from '@/hooks/useNamespaces';

interface NamespaceSelectorProps {
  namespace: string;
  onNamespaceChange: (namespace: string) => void;
  enabledOnly?: boolean;
  minWidth?: string;
}

export const NamespaceSelector: React.FC<NamespaceSelectorProps> = ({
  namespace,
  onNamespaceChange,
  enabledOnly = true,
  minWidth = '200px',
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const { data: namespaces = [], isLoading } = useNamespaces(enabledOnly);

  const onSelect = (
    _event: React.MouseEvent | undefined,
    value: string | number | undefined
  ) => {
    if (value) {
      onNamespaceChange(value as string);
    }
    setIsOpen(false);
  };

  return (
    <Select
      aria-label="Select namespace"
      isOpen={isOpen}
      selected={namespace}
      onSelect={onSelect}
      onOpenChange={(open) => setIsOpen(open)}
      toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
        <MenuToggle
          ref={toggleRef}
          onClick={() => setIsOpen(!isOpen)}
          isExpanded={isOpen}
          isDisabled={isLoading}
          style={{ minWidth }}
        >
          {isLoading ? 'Loading...' : namespace || 'Select namespace'}
        </MenuToggle>
      )}
    >
      <SelectList>
        {namespaces.map((ns) => (
          <SelectOption key={ns} value={ns}>
            {ns}
          </SelectOption>
        ))}
      </SelectList>
    </Select>
  );
};
