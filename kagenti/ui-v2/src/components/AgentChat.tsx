// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useRef, useEffect } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  TextArea,
  Button,
  Split,
  SplitItem,
  Alert,
  Spinner,
  Label,
  ExpandableSection,
} from '@patternfly/react-core';
import { PaperPlaneIcon } from '@patternfly/react-icons';
import { useQuery, useMutation } from '@tanstack/react-query';

import { chatService } from '@/services/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface AgentChatProps {
  namespace: string;
  name: string;
}

export const AgentChat: React.FC<AgentChatProps> = ({ namespace, name }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [showAgentCard, setShowAgentCard] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Fetch agent card to check capabilities
  const { data: agentCard, isLoading: isLoadingCard, error: cardError } = useQuery({
    queryKey: ['agent-card', namespace, name],
    queryFn: () => chatService.getAgentCard(namespace, name),
  });

  const sendMessageMutation = useMutation({
    mutationFn: (message: string) =>
      chatService.sendMessage(namespace, name, message, sessionId || undefined),
    onSuccess: (response) => {
      setSessionId(response.session_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: response.content,
          timestamp: new Date(),
        },
      ]);
    },
  });

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleSendMessage = async () => {
    if (!input.trim() || isStreaming || sendMessageMutation.isPending) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const messageToSend = input.trim();
    setInput('');

    // Check if agent supports streaming
    if (agentCard?.streaming) {
      // Use streaming
      setIsStreaming(true);
      setStreamingContent('');

      try {
        const response = await fetch(
          `/api/v1/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/stream`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              message: messageToSend,
              session_id: sessionId,
            }),
          }
        );

        if (!response.ok) {
          throw new Error(`HTTP error: ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let accumulatedContent = '';

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));

                  if (data.session_id) {
                    setSessionId(data.session_id);
                  }

                  if (data.content) {
                    accumulatedContent += data.content;
                    setStreamingContent(accumulatedContent);
                  }

                  if (data.error) {
                    accumulatedContent = `Error: ${data.error}`;
                    setStreamingContent(accumulatedContent);
                  }

                  if (data.done) {
                    break;
                  }
                } catch {
                  // Ignore parse errors for incomplete chunks
                }
              }
            }
          }
        }

        // Add the complete message
        if (accumulatedContent) {
          setMessages((prev) => [
            ...prev,
            {
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: accumulatedContent,
              timestamp: new Date(),
            },
          ]);
        }
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: `Error: ${error instanceof Error ? error.message : 'Failed to get response'}`,
            timestamp: new Date(),
          },
        ]);
      } finally {
        setIsStreaming(false);
        setStreamingContent('');
      }
    } else {
      // Use non-streaming
      sendMessageMutation.mutate(messageToSend);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  if (isLoadingCard) {
    return (
      <Card>
        <CardBody>
          <div style={{ textAlign: 'center', padding: '32px' }}>
            <Spinner size="lg" />
            <p style={{ marginTop: '16px' }}>Loading agent capabilities...</p>
          </div>
        </CardBody>
      </Card>
    );
  }

  if (cardError) {
    return (
      <Card>
        <CardBody>
          <Alert variant="danger" title="Failed to load agent" isInline>
            {cardError instanceof Error
              ? cardError.message
              : 'Could not connect to the agent. Make sure the agent is running and accessible.'}
          </Alert>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>
        <Split hasGutter>
          <SplitItem>Chat with {agentCard?.name || name}</SplitItem>
          <SplitItem isFilled />
          <SplitItem>
            {agentCard?.streaming && (
              <Label color="blue" isCompact>
                Streaming
              </Label>
            )}
          </SplitItem>
        </Split>
      </CardTitle>
      <CardBody>
        {/* Agent Card Info */}
        {agentCard && (
          <ExpandableSection
            toggleText="Agent Details"
            isExpanded={showAgentCard}
            onToggle={() => setShowAgentCard(!showAgentCard)}
            style={{ marginBottom: '16px' }}
          >
            <div
              style={{
                padding: '12px',
                backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                borderRadius: '4px',
              }}
            >
              <p>
                <strong>Description:</strong> {agentCard.description || 'No description'}
              </p>
              <p>
                <strong>Version:</strong> {agentCard.version}
              </p>
              {agentCard.skills.length > 0 && (
                <div>
                  <strong>Skills:</strong>
                  <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                    {agentCard.skills.map((skill) => (
                      <li key={skill.id}>
                        <strong>{skill.name}</strong>
                        {skill.description && `: ${skill.description}`}
                        {skill.examples && skill.examples.length > 0 && (
                          <div style={{ fontSize: '0.85em', color: 'var(--pf-v5-global--Color--200)' }}>
                            Examples: {skill.examples.join(', ')}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </ExpandableSection>
        )}

        {/* Messages Container */}
        <div
          style={{
            height: '400px',
            overflowY: 'auto',
            border: '1px solid var(--pf-v5-global--BorderColor--100)',
            borderRadius: '4px',
            padding: '16px',
            marginBottom: '16px',
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
          }}
        >
          {messages.length === 0 && !isStreaming ? (
            <div
              style={{
                textAlign: 'center',
                color: 'var(--pf-v5-global--Color--200)',
                padding: '32px',
              }}
            >
              <p>Start a conversation with the agent.</p>
              {agentCard?.skills && agentCard.skills.length > 0 && (
                <p style={{ marginTop: '8px', fontSize: '0.9em' }}>
                  Try asking about: {agentCard.skills.map((s) => s.name).join(', ')}
                </p>
              )}
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <div
                  key={message.id}
                  style={{
                    marginBottom: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: message.role === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '80%',
                      padding: '12px 16px',
                      borderRadius: '12px',
                      backgroundColor:
                        message.role === 'user'
                          ? 'var(--pf-v5-global--primary-color--100)'
                          : 'var(--pf-v5-global--BackgroundColor--200)',
                      color:
                        message.role === 'user'
                          ? 'white'
                          : 'var(--pf-v5-global--Color--100)',
                    }}
                  >
                    <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>
                  </div>
                  <div
                    style={{
                      fontSize: '0.75em',
                      color: 'var(--pf-v5-global--Color--200)',
                      marginTop: '4px',
                    }}
                  >
                    {message.timestamp.toLocaleTimeString()}
                  </div>
                </div>
              ))}

              {/* Streaming message */}
              {isStreaming && streamingContent && (
                <div
                  style={{
                    marginBottom: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '80%',
                      padding: '12px 16px',
                      borderRadius: '12px',
                      backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                    }}
                  >
                    <div style={{ whiteSpace: 'pre-wrap' }}>{streamingContent}</div>
                    <span
                      style={{
                        display: 'inline-block',
                        width: '8px',
                        height: '16px',
                        backgroundColor: 'var(--pf-v5-global--primary-color--100)',
                        animation: 'blink 1s infinite',
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Loading indicator for non-streaming */}
              {sendMessageMutation.isPending && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    color: 'var(--pf-v5-global--Color--200)',
                  }}
                >
                  <Spinner size="sm" />
                  <span>Agent is thinking...</span>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <Split hasGutter>
          <SplitItem isFilled>
            <TextArea
              value={input}
              onChange={(_e, value) => setInput(value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your message..."
              aria-label="Chat message input"
              rows={2}
              isDisabled={isStreaming || sendMessageMutation.isPending}
              style={{ resize: 'vertical' }}
            />
          </SplitItem>
          <SplitItem>
            <Button
              variant="primary"
              onClick={handleSendMessage}
              isDisabled={!input.trim() || isStreaming || sendMessageMutation.isPending}
              isLoading={isStreaming || sendMessageMutation.isPending}
              icon={<PaperPlaneIcon />}
              style={{ height: '100%' }}
            >
              Send
            </Button>
          </SplitItem>
        </Split>

        {/* Error display */}
        {sendMessageMutation.isError && (
          <Alert
            variant="danger"
            title="Failed to send message"
            isInline
            style={{ marginTop: '16px' }}
          >
            {sendMessageMutation.error instanceof Error
              ? sendMessageMutation.error.message
              : 'An unexpected error occurred'}
          </Alert>
        )}

        <style>
          {`
            @keyframes blink {
              0%, 50% { opacity: 1; }
              51%, 100% { opacity: 0; }
            }
          `}
        </style>
      </CardBody>
    </Card>
  );
};
