import React, { useState, Component, type ErrorInfo, type ReactNode } from 'react';
import { Modal, ModalVariant, Button, Spinner, Tooltip } from '@patternfly/react-core';
import { ExpandIcon, CompressIcon, ExternalLinkAltIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { sandboxFileService } from '@/services/api';
import type { FileContent } from '@/types';
import { FilePreview } from './FilePreview';

/**
 * Minimal error boundary for file preview rendering.
 * Kept inline to avoid circular dependencies with FileBrowser.
 */
interface PreviewErrorBoundaryProps {
  children: ReactNode;
}

interface PreviewErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class PreviewErrorBoundary extends Component<PreviewErrorBoundaryProps, PreviewErrorBoundaryState> {
  constructor(props: PreviewErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): PreviewErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('FilePreviewModal: preview render error', error, errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '1rem', color: 'var(--pf-v5-global--danger-color--100)' }}>
          <strong>Preview failed to render</strong>
          {this.state.error && <pre style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap' }}>{this.state.error.message}</pre>}
        </div>
      );
    }
    return this.props.children;
  }
}

export interface FilePreviewModalProps {
  filePath: string | null;
  namespace: string;
  agentName: string;
  contextId?: string;
  isOpen: boolean;
  onClose: () => void;
}

const fullscreenStyles: React.CSSProperties = {
  width: '100vw',
  maxWidth: '100vw',
  height: '100vh',
  maxHeight: '100vh',
  margin: 0,
  borderRadius: 0,
};

export const FilePreviewModal: React.FC<FilePreviewModalProps> = ({
  filePath,
  namespace,
  agentName,
  contextId,
  isOpen,
  onClose,
}) => {
  const [isFullScreen, setIsFullScreen] = useState(false);

  const {
    data: fileContent,
    isLoading,
    error,
  } = useQuery<FileContent>({
    queryKey: ['filePreview', namespace, agentName, contextId, filePath],
    queryFn: () =>
      sandboxFileService.getFileContent(namespace, agentName, contextId ?? '', filePath ?? ''),
    enabled: isOpen && !!filePath,
  });

  if (!isOpen || !filePath) {
    return null;
  }

  const fileName = filePath.split('/').pop() ?? filePath;

  const fileBrowserPath = contextId
    ? `/sandbox/files/${namespace}/${agentName}/${contextId}?path=${encodeURIComponent(filePath)}`
    : `/sandbox/files/${namespace}/${agentName}?path=${encodeURIComponent(filePath)}`;

  const headerActions = (
    <React.Fragment>
      <Tooltip content={isFullScreen ? 'Exit fullscreen' : 'Fullscreen'}>
        <Button
          variant="plain"
          aria-label={isFullScreen ? 'Exit fullscreen' : 'Fullscreen'}
          onClick={() => setIsFullScreen((prev) => !prev)}
        >
          {isFullScreen ? <CompressIcon /> : <ExpandIcon />}
        </Button>
      </Tooltip>
      <Tooltip content="Open in File Browser">
        <Link to={fileBrowserPath} onClick={onClose}>
          <Button variant="plain" aria-label="Open in File Browser" component="span">
            <ExternalLinkAltIcon />
          </Button>
        </Link>
      </Tooltip>
    </React.Fragment>
  );

  const renderBody = () => {
    if (isLoading) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px' }}>
          <Spinner size="lg" aria-label="Loading file content" />
        </div>
      );
    }

    if (error) {
      return (
        <div style={{ padding: '1rem', color: 'var(--pf-v5-global--danger-color--100)' }}>
          <strong>Failed to load file</strong>
          <pre style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap' }}>
            {error instanceof Error ? error.message : String(error)}
          </pre>
        </div>
      );
    }

    if (!fileContent) {
      return null;
    }

    return (
      <PreviewErrorBoundary>
        <FilePreview content={fileContent} filePath={filePath} />
      </PreviewErrorBoundary>
    );
  };

  return (
    <Modal
      variant={ModalVariant.large}
      title={fileName}
      isOpen={isOpen}
      onClose={onClose}
      actions={[headerActions]}
      style={isFullScreen ? fullscreenStyles : undefined}
    >
      {renderBody()}
    </Modal>
  );
};

export default FilePreviewModal;
