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
import { EventsPanel, A2AEvent } from './EventsPanel';
import { useAuth } from '@/contexts/AuthContext';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Markdown styling for chat messages
const markdownStyles: React.CSSProperties = {
  lineHeight: '1.6',
};

const markdownComponents = {
  // Style paragraphs
  p: ({ children }: any) => <p style={{ margin: '0.5em 0' }}>{children}</p>,
  // Style lists
  ul: ({ children }: any) => <ul style={{ margin: '0.5em 0', paddingLeft: '1.5em' }}>{children}</ul>,
  ol: ({ children }: any) => <ol style={{ margin: '0.5em 0', paddingLeft: '1.5em' }}>{children}</ol>,
  // Style list items
  li: ({ children }: any) => <li style={{ margin: '0.25em 0' }}>{children}</li>,
  // Style code blocks - use theme-aware CSS variables
  code: ({ inline, children }: any) =>
    inline ? (
      <code style={{
        backgroundColor: 'var(--kagenti-code-bg)',
        color: 'var(--kagenti-code-color)',
        padding: '2px 6px',
        borderRadius: '3px',
        fontSize: '0.9em',
      }}>{children}</code>
    ) : (
      <code style={{
        display: 'block',
        backgroundColor: 'var(--kagenti-code-bg)',
        color: 'var(--kagenti-code-color)',
        padding: '12px',
        borderRadius: '6px',
        fontSize: '0.9em',
        overflowX: 'auto',
        margin: '0.5em 0',
      }}>{children}</code>
    ),
  // Style strong/bold text
  strong: ({ children }: any) => <strong style={{ fontWeight: 600 }}>{children}</strong>,
};

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  events?: A2AEvent[];
  isComplete?: boolean;
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
  const [streamingEvents, setStreamingEvents] = useState<A2AEvent[]>([]);
  const [showAgentCard, setShowAgentCard] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { getToken } = useAuth();

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
          isComplete: true,
        },
      ]);
    },
  });

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent, streamingEvents]);

  const handleSendMessage = async () => {
    if (!input.trim() || isStreaming || sendMessageMutation.isPending) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
      isComplete: true,
    };

    setMessages((prev) => [...prev, userMessage]);
    const messageToSend = input.trim();
    setInput('');

    // Check if agent supports streaming
    if (agentCard?.streaming) {
      // Use streaming
      setIsStreaming(true);
      setStreamingContent('');
      setStreamingEvents([]);

      try {
        // Get auth token if available
        const token = await getToken();
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
        };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }

        const response = await fetch(
          `/api/v1/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/stream`,
          {
            method: 'POST',
            headers,
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
        const collectedEvents: A2AEvent[] = [];
        let buffer = ''; // Buffer for incomplete SSE lines

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            buffer += chunk;

            // Split on double newline (SSE message separator) or single newline
            const lines = buffer.split('\n');
            // Keep the last potentially incomplete line in the buffer
            buffer = lines.pop() || '';

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));
                  console.log('[AgentChat] Received SSE data:', data);

                  if (data.session_id) {
                    setSessionId(data.session_id);
                  }

                  // Process event if present
                  if (data.event) {
                    console.log('[AgentChat] Processing event:', data.event);
                    const event: A2AEvent = {
                      id: `event-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                      timestamp: new Date(),
                      type: data.event.type,
                      taskId: data.event.taskId,
                      state: data.event.state,
                      message: data.event.message,
                      final: data.event.final || data.event.type === 'artifact', // Artifacts are final
                    };

                    // Add artifact info if present
                    if (data.event.type === 'artifact') {
                      event.artifactName = data.event.name;
                      if (data.content) {
                        event.artifactContent = data.content;
                      }
                    }

                    collectedEvents.push(event);
                    console.log('[AgentChat] Added event to collection, total events:', collectedEvents.length, event);
                    setStreamingEvents([...collectedEvents]);
                  } else {
                    console.log('[AgentChat] No event field in data, skipping event creation');
                  }

                  // Accumulate content (for final message)
                  if (data.content) {
                    // Accumulate content from: final events, non-artifact events, OR artifact events
                    // Artifacts contain the final answer from the agent
                    if (!data.event || data.event.final || data.event.type === 'artifact') {
                      accumulatedContent += data.content;
                      setStreamingContent(accumulatedContent);
                    }
                  }

                  if (data.error) {
                    // Add error event
                    const errorEvent: A2AEvent = {
                      id: `event-error-${Date.now()}`,
                      timestamp: new Date(),
                      type: 'error',
                      message: data.error,
                    };
                    collectedEvents.push(errorEvent);
                    setStreamingEvents([...collectedEvents]);

                    accumulatedContent = `Error: ${data.error}`;
                    setStreamingContent(accumulatedContent);
                  }

                  if (data.done) {
                    break;
                  }
                } catch (parseError) {
                  // Log parse errors for debugging (may be incomplete chunks)
                  console.log('[AgentChat] Parse error for line:', line.slice(0, 200), parseError);
                }
              }
            }
          }
        }

        // Add the complete message with events
        if (accumulatedContent || collectedEvents.length > 0) {
          setMessages((prev) => [
            ...prev,
            {
              id: `assistant-${Date.now()}`,
              role: 'assistant',
              content: accumulatedContent || 'No response from agent',
              timestamp: new Date(),
              events: collectedEvents,
              isComplete: true,
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
            isComplete: true,
          },
        ]);
      } finally {
        setIsStreaming(false);
        setStreamingContent('');
        setStreamingEvents([]);
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
                    {/* Events Panel for assistant messages with events */}
                    {message.role === 'assistant' && message.events && message.events.length > 0 && (
                      <EventsPanel
                        events={message.events}
                        isComplete={message.isComplete ?? true}
                        defaultExpanded={false}
                      />
                    )}
                    {message.role === 'assistant' ? (
                      <div style={markdownStyles}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div style={{ whiteSpace: 'pre-wrap' }}>{message.content}</div>
                    )}
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

              {/* Streaming message with live events */}
              {isStreaming && (
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
                    {/* Live events panel */}
                    {streamingEvents.length > 0 && (
                      <EventsPanel
                        events={streamingEvents}
                        isComplete={false}
                        defaultExpanded={true}
                      />
                    )}
                    {streamingContent ? (
                      <div style={markdownStyles}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {streamingContent}
                        </ReactMarkdown>
                        <span
                          style={{
                            display: 'inline-block',
                            width: '8px',
                            height: '16px',
                            backgroundColor: 'var(--pf-v5-global--primary-color--100)',
                            animation: 'blink 1s infinite',
                            marginLeft: '2px',
                          }}
                        />
                      </div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Spinner size="sm" />
                        <span>Processing...</span>
                      </div>
                    )}
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
