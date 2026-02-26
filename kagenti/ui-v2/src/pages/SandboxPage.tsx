// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  PageSection,
  Title,
  Card,
  CardBody,
  TextArea,
  Button,
  Split,
  SplitItem,
  Spinner,
  Alert,
} from '@patternfly/react-core';
import { PaperPlaneIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { sandboxService } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { SessionSidebar } from '../components/SessionSidebar';
import { SandboxConfig, SandboxConfigValues } from '../components/SandboxConfig';
import { NamespaceSelector } from '../components/NamespaceSelector';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export const SandboxPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [namespace, setNamespace] = useState('team1');
  const [contextId, setContextId] = useState(
    searchParams.get('session') || ''
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { getToken } = useAuth();
  const [config, setConfig] = useState<SandboxConfigValues>({
    model: 'gpt-4o-mini',
    repo: '',
    branch: 'main',
  });

  // Load session history when selecting an existing session
  const { data: sessionDetail } = useQuery({
    queryKey: ['sandbox-session', namespace, contextId],
    queryFn: () => sandboxService.getSession(namespace, contextId),
    enabled: !!contextId && !!namespace,
  });

  useEffect(() => {
    if (sessionDetail?.history) {
      const loaded: Message[] = sessionDetail.history.map((h, i) => ({
        id: `history-${i}`,
        role: h.role as 'user' | 'assistant',
        content:
          h.parts
            ?.map((p) => p.text)
            .filter(Boolean)
            .join('') || '',
        timestamp: new Date(),
      }));
      setMessages(loaded);
    }
  }, [sessionDetail]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleSelectSession = useCallback(
    (id: string) => {
      setContextId(id);
      setMessages([]);
      setError(null);
      if (id) {
        setSearchParams({ session: id });
      } else {
        setSearchParams({});
      }
    },
    [setSearchParams]
  );

  const handleSendMessage = async () => {
    if (!input.trim() || isStreaming) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    const messageToSend = input.trim();
    setInput('');
    setIsStreaming(true);
    setStreamingContent('');
    setError(null);

    try {
      const token = await getToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(
        `/api/v1/sandbox/${encodeURIComponent(namespace)}/chat`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({
            message: messageToSend,
            session_id: contextId || undefined,
            agent_name: 'sandbox-legion',
          }),
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP error: ${response.status}`);
      }

      const data = await response.json();

      if (data.context_id && !contextId) {
        setContextId(data.context_id);
        setSearchParams({ session: data.context_id });
      }

      if (data.content) {
        setMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: data.content,
            timestamp: new Date(),
          },
        ]);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to send';
      setError(msg);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          content: `Error: ${msg}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
    }
  };

  return (
    <PageSection variant="light" padding={{ default: 'noPadding' }}>
      <div style={{ display: 'flex', height: 'calc(100vh - 80px)' }}>
        <SessionSidebar
          namespace={namespace}
          activeContextId={contextId}
          onSelectSession={handleSelectSession}
        />

        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            padding: 16,
          }}
        >
          {/* Header */}
          <Split hasGutter style={{ marginBottom: 8 }}>
            <SplitItem>
              <Title headingLevel="h1" size="xl">
                Sandbox Legion
              </Title>
            </SplitItem>
            <SplitItem isFilled />
            <SplitItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
            </SplitItem>
          </Split>

          <SandboxConfig config={config} onChange={setConfig} />

          {error && (
            <Alert
              variant="danger"
              title={error}
              isInline
              style={{ marginBottom: 8 }}
            />
          )}

          {/* Chat messages */}
          <Card style={{ flex: 1, overflow: 'hidden' }}>
            <CardBody
              style={{
                height: '100%',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {messages.length === 0 && !isStreaming && (
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--pf-v5-global--Color--200)',
                  }}
                >
                  Start a conversation with Sandbox Legion
                </div>
              )}

              {messages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    padding: '8px 12px',
                    marginBottom: 8,
                    backgroundColor:
                      msg.role === 'user'
                        ? 'var(--pf-v5-global--BackgroundColor--200)'
                        : 'transparent',
                    borderRadius: 4,
                  }}
                >
                  <strong>{msg.role === 'user' ? 'You' : 'Legion'}:</strong>
                  {msg.role === 'assistant' ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  ) : (
                    <p style={{ margin: '4px 0 0' }}>{msg.content}</p>
                  )}
                </div>
              ))}

              {isStreaming && (
                <div style={{ padding: '8px 12px' }}>
                  <strong>Legion:</strong>
                  {streamingContent ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {streamingContent}
                    </ReactMarkdown>
                  ) : (
                    <Spinner size="sm" style={{ marginLeft: 8 }} />
                  )}
                </div>
              )}

              <div ref={messagesEndRef} />
            </CardBody>
          </Card>

          {/* Input area */}
          <Split hasGutter style={{ marginTop: 8 }}>
            <SplitItem isFilled>
              <TextArea
                value={input}
                onChange={(_e, value) => setInput(value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder="Type your message... (Enter to send, Shift+Enter for newline)"
                aria-label="Message input"
                rows={2}
                isDisabled={isStreaming}
              />
            </SplitItem>
            <SplitItem>
              <Button
                variant="primary"
                onClick={handleSendMessage}
                isDisabled={isStreaming || !input.trim()}
                icon={<PaperPlaneIcon />}
              >
                Send
              </Button>
            </SplitItem>
          </Split>
        </div>
      </div>
    </PageSection>
  );
};
