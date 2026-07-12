// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  Modal,
  ModalVariant,
  Button,
  Form,
  FormGroup,
  TextArea,
  FormHelperText,
  HelperText,
  HelperTextItem,
  Alert,
} from '@patternfly/react-core';
import { useMutation } from '@tanstack/react-query';
import { simulationService } from '@/services/api';
import { parseSeedDatabase, extractReseedError } from '@/utils/simulation';

export interface SeedDatabaseModalProps {
  isOpen: boolean;
  namespace: string;
  name: string;
  onClose: () => void;
  onSuccess?: () => void;
}

const SeedDatabaseModal: React.FC<SeedDatabaseModalProps> = ({
  isOpen,
  namespace,
  name,
  onClose,
  onSuccess,
}) => {
  const [text, setText] = React.useState('');
  const [fileError, setFileError] = React.useState('');
  const [serverError, setServerError] = React.useState<{ message: string; jsonPath?: string } | null>(null);

  const parsed = parseSeedDatabase(text);
  const parseError = text.trim() && !parsed.ok ? parsed.error : '';

  const reseedMutation = useMutation({
    mutationFn: () => simulationService.reseedDatabase(namespace, name, text),
    onSuccess: () => {
      handleClose();
      onSuccess?.();
    },
    onError: (err) => setServerError(extractReseedError(err)),
  });

  const handleClose = () => {
    setText('');
    setFileError('');
    setServerError(null);
    onClose();
  };

  const handleApply = () => {
    setServerError(null);
    reseedMutation.mutate();
  };

  return (
    <Modal
      variant={ModalVariant.medium}
      title="Seed / edit database"
      isOpen={isOpen}
      onClose={handleClose}
      description="Replace this simulated tool's database with your own test dataset. The dataset is validated against the tool's schema and the session is reset."
      actions={[
        <Button
          key="apply"
          variant="primary"
          onClick={handleApply}
          isLoading={reseedMutation.isPending}
          isDisabled={reseedMutation.isPending || !parsed.ok}
        >
          Apply dataset
        </Button>,
        <Button key="cancel" variant="link" onClick={handleClose} isDisabled={reseedMutation.isPending}>
          Cancel
        </Button>,
      ]}
    >
      <Form>
        <FormGroup label="db.json" isRequired fieldId="seed-db-json">
          <TextArea
            id="seed-db-json"
            aria-label="Database JSON"
            value={text}
            onChange={(_e, value) => {
              setText(value);
              setFileError('');
              setServerError(null);
            }}
            rows={14}
            placeholder='Paste db.json here, or upload a file below'
            validated={parseError ? 'error' : 'default'}
          />
          <input
            type="file"
            accept=".json,application/json"
            aria-label="Upload db.json file"
            style={{ marginTop: '8px' }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              // Reset so re-selecting the same file re-fires onChange.
              e.target.value = '';
              if (!file) return;
              const reader = new FileReader();
              reader.onload = () => {
                setFileError('');
                setServerError(null);
                setText(String(reader.result ?? ''));
              };
              reader.onerror = () => {
                setFileError('Failed to read the selected file. Please try again or paste the dataset directly.');
              };
              reader.readAsText(file);
            }}
          />
          <FormHelperText>
            <HelperText>
              <HelperTextItem variant={fileError || parseError ? 'error' : 'default'}>
                {fileError || parseError || 'Paste a db.json document (a JSON object), or upload a file.'}
              </HelperTextItem>
            </HelperText>
          </FormHelperText>
        </FormGroup>
        {serverError && (
          <Alert
            variant="danger"
            isInline
            title={
              serverError.jsonPath
                ? `Dataset invalid at ${serverError.jsonPath}`
                : 'Re-seed failed'
            }
          >
            {serverError.message}
          </Alert>
        )}
      </Form>
    </Modal>
  );
};

export default SeedDatabaseModal;
