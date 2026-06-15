import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Button,
  Card,
  CardBody,
  TextArea,
  Title,
  Text,
  TextContent,
  Spinner,
  Alert,
  Flex,
  FlexItem,
  Divider,
} from '@patternfly/react-core';
import { ArrowLeftIcon, PaperPlaneIcon } from '@patternfly/react-icons';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';

import { chatService, tokenBrokerService } from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';

export const ChatPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const { tokenBrokerEnabled } = useAuth();

  const [message, setMessage] = useState('');
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [responses, setResponses] = useState<
    Array<{ role: 'user' | 'agent'; text: string }>
  >([]);
  const [oauthStatus, setOauthStatus] = useState<string | null>(null);
  const pollingRef = useRef(false);

  const startPolling = useCallback(() => {
    if (pollingRef.current) return;
    pollingRef.current = true;

    const poll = async () => {
      let sessionRecreateAttempts = 0;
      const MAX_RECREATE_ATTEMPTS = 3;
      const redirectUrl = window.location.origin + '/oauth-complete.html';

      while (pollingRef.current) {
        try {
          const event = await tokenBrokerService.pollEvents();
          if (!pollingRef.current) break;

          // Reset recreate attempts on successful poll
          sessionRecreateAttempts = 0;

          if (event && event.type === 'oauth_url_ready' && event.auth_url) {
            window.open(event.auth_url, '_blank', 'width=600,height=700');
          } else if (event && event.type === 'error') {
            setOauthStatus(`OAuth error: ${event.message || 'unknown'}`);
          }
        } catch (error: any) {
          if (!pollingRef.current) break;

          // Check if it's a 404 (no active session)
          const is404 = error?.message?.includes('404');

          if (is404 && sessionRecreateAttempts < MAX_RECREATE_ATTEMPTS) {
            sessionRecreateAttempts++;
            console.log(`[TokenBroker] Session lost, recreating... (attempt ${sessionRecreateAttempts}/${MAX_RECREATE_ATTEMPTS})`);

            try {
              const created = await tokenBrokerService.createSession(redirectUrl);
              if (created) {
                console.log('[TokenBroker] Session recreated successfully, resuming polling');
                sessionRecreateAttempts = 0; // Reset on success
                continue; // Continue polling immediately
              } else {
                console.warn('[TokenBroker] Session recreation failed (503), will retry with backoff');
              }
            } catch (createError) {
              console.error('[TokenBroker] Session recreation error:', createError);
            }

            // Exponential backoff: 2s, 4s, 8s
            const backoffMs = 2000 * Math.pow(2, sessionRecreateAttempts - 1);
            await new Promise((r) => setTimeout(r, backoffMs));
          } else if (sessionRecreateAttempts >= MAX_RECREATE_ATTEMPTS) {
            console.error('[TokenBroker] Max session recreation attempts reached, stopping polling');
            setOauthStatus('Token Broker session lost. Please refresh the page.');
            pollingRef.current = false;
            break;
          } else {
            // Other errors: retry with fixed delay
            await new Promise((r) => setTimeout(r, 2000));
          }
        }
      }
    };
    poll();
  }, []);

  useEffect(() => {
    console.log('[ChatPage] Token Broker enabled:', tokenBrokerEnabled);
    if (!tokenBrokerEnabled) {
      console.log('[ChatPage] Token Broker disabled, skipping polling');
      return;
    }

    // Token Broker session is already created in AuthContext after login
    // Just start polling for events
    console.log('[ChatPage] Starting Token Broker polling...');
    startPolling();

    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === 'oauth-complete') {
        setOauthStatus(
          e.data.status === 'success'
            ? 'OAuth completed successfully'
            : `OAuth failed: ${e.data.error_description || e.data.error || 'unknown'}`,
        );
      }
    };
    window.addEventListener('message', handleMessage);

    return () => {
      pollingRef.current = false;
      window.removeEventListener('message', handleMessage);
      // Don't end session here - it should persist across chat pages
    };
  }, [tokenBrokerEnabled, startPolling]);

  const sendMutation = useMutation({
    mutationFn: () =>
      chatService.sendMessage(namespace!, name!, message, sessionId),
    onSuccess: (data) => {
      setResponses((prev) => [
        ...prev,
        { role: 'user', text: message },
        { role: 'agent', text: data.content },
      ]);
      setSessionId(data.session_id);
      setMessage('');
    },
  });

  const handleSend = () => {
    if (!message.trim()) return;
    sendMutation.mutate();
  };

  const handleNewTask = () => {
    setResponses([]);
    setSessionId(undefined);
    setMessage('');
  };

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      <Flex
        alignItems={{ default: 'alignItemsCenter' }}
        style={{ marginBottom: '16px' }}
      >
        <FlexItem>
          <Button
            variant="link"
            icon={<ArrowLeftIcon />}
            onClick={() => navigate('/agents')}
          >
            Back to Agents
          </Button>
        </FlexItem>
      </Flex>

      <div style={{ marginBottom: '24px' }}>
        <Title headingLevel="h1" size="2xl">
          {name}
        </Title>
        <TextContent>
          <Text component="small" style={{ color: '#6a6e73' }}>
            {namespace}
          </Text>
        </TextContent>
      </div>

      <Divider style={{ marginBottom: '24px' }} />

      {responses.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          {responses.map((r, i) => (
            <div
              key={i}
              style={{
                marginBottom: '12px',
                display: 'flex',
                justifyContent: r.role === 'user' ? 'flex-end' : 'flex-start',
              }}
            >
              <Card
                style={{
                  maxWidth: '80%',
                  background:
                    r.role === 'user'
                      ? '#0066cc'
                      : 'var(--pf-v5-global--BackgroundColor--200, #f0f0f0)',
                  color: r.role === 'user' ? '#fff' : 'inherit',
                }}
              >
                <CardBody>
                  <TextContent>
                    <Text
                      component="small"
                      style={{
                        fontWeight: 600,
                        marginBottom: '4px',
                        color:
                          r.role === 'user'
                            ? 'rgba(255,255,255,0.8)'
                            : '#6a6e73',
                      }}
                    >
                      {r.role === 'user' ? 'You' : name}
                    </Text>
                    <Text
                      style={{
                        whiteSpace: 'pre-wrap',
                        color: r.role === 'user' ? '#fff' : 'inherit',
                      }}
                    >
                      {r.text}
                    </Text>
                  </TextContent>
                </CardBody>
              </Card>
            </div>
          ))}
        </div>
      )}

      {oauthStatus && (
        <Alert
          variant={oauthStatus.startsWith('OAuth completed') ? 'success' : 'warning'}
          title={oauthStatus}
          style={{ marginBottom: '16px' }}
        />
      )}

      {sendMutation.isError && (
        <Alert
          variant="danger"
          title={
            sendMutation.error?.message?.includes('403') ||
            sendMutation.error?.message?.includes('401')
              ? 'Access denied'
              : 'Failed to send message'
          }
          style={{ marginBottom: '16px' }}
        >
          {sendMutation.error?.message?.includes('403') ||
          sendMutation.error?.message?.includes('401')
            ? 'You do not have permission to interact with this agent.'
            : (sendMutation.error?.message || 'An unexpected error occurred.')}
        </Alert>
      )}

      <Card>
        <CardBody>
          <TextArea
            value={message}
            onChange={(_event, value) => setMessage(value)}
            placeholder="Describe your task..."
            aria-label="Task message"
            rows={4}
            isDisabled={sendMutation.isPending}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <Flex
            justifyContent={{ default: 'justifyContentFlexEnd' }}
            style={{ marginTop: '12px', gap: '8px' }}
          >
            {responses.length > 0 && (
              <FlexItem>
                <Button
                  variant="secondary"
                  onClick={handleNewTask}
                  isDisabled={sendMutation.isPending}
                >
                  New Task
                </Button>
              </FlexItem>
            )}
            <FlexItem>
              <Button
                variant="primary"
                icon={sendMutation.isPending ? <Spinner size="sm" /> : <PaperPlaneIcon />}
                onClick={handleSend}
                isDisabled={!message.trim() || sendMutation.isPending}
              >
                {sendMutation.isPending ? 'Sending...' : 'Send'}
              </Button>
            </FlexItem>
          </Flex>
        </CardBody>
      </Card>
    </div>
  );
};
