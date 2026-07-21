// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  ExpandableSection,
  Form,
  FormGroup,
  FormSelect,
  FormSelectOption,
  TextInput,
} from '@patternfly/react-core';

export interface SandboxConfigValues {
  model: string;
  repo: string;
  branch: string;
}

interface SandboxConfigProps {
  config: SandboxConfigValues;
  onChange: (config: SandboxConfigValues) => void;
}

const MODEL_OPTIONS = [
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
];

export const SandboxConfig: React.FC<SandboxConfigProps> = ({
  config,
  onChange,
}) => {
  return (
    <ExpandableSection toggleText="Advanced Configuration" isIndented>
      <Form isHorizontal style={{ padding: '8px 0' }}>
        <FormGroup label="Model" fieldId="sandbox-model">
          <FormSelect
            id="sandbox-model"
            value={config.model}
            onChange={(_e, value) =>
              onChange({ ...config, model: value })
            }
          >
            {MODEL_OPTIONS.map((opt) => (
              <FormSelectOption
                key={opt.value}
                value={opt.value}
                label={opt.label}
              />
            ))}
          </FormSelect>
        </FormGroup>

        <FormGroup label="Repository" fieldId="sandbox-repo">
          <TextInput
            id="sandbox-repo"
            value={config.repo}
            onChange={(_e, value) =>
              onChange({ ...config, repo: value })
            }
            placeholder="https://github.com/org/repo"
          />
        </FormGroup>

        <FormGroup label="Branch" fieldId="sandbox-branch">
          <TextInput
            id="sandbox-branch"
            value={config.branch}
            onChange={(_e, value) =>
              onChange({ ...config, branch: value })
            }
            placeholder="main"
          />
        </FormGroup>
      </Form>
    </ExpandableSection>
  );
};
