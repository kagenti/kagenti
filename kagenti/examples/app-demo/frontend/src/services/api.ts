import type { Agent, AuthConfig, ChatResponse, TokenBrokerEvent } from '@/types';

const API_BASE = '/api/v1';

let tokenGetter: (() => Promise<string | null>) | null = null;

export function setTokenGetter(getter: () => Promise<string | null>): void {
  tokenGetter = getter;
}

async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (tokenGetter) {
    try {
      const token = await tokenGetter();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    } catch (error) {
      // Token refresh failed and triggered re-login
      // Re-throw to let caller handle it
      throw error;
    }
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));

    // Check for token expiration errors
    if (response.status === 401 ||
        (errorData.detail &&
         (errorData.detail.includes('Signature has expired') ||
          errorData.detail.includes('Invalid token')))) {
      // Token expired - trigger re-login via tokenGetter
      if (tokenGetter) {
        try {
          await tokenGetter();
        } catch {
          // Re-login triggered, don't throw additional error
        }
      }
      throw new Error('Your session has expired. Please log in again.');
    }

    throw new Error(
      errorData.detail || `API error: ${response.status} ${response.statusText}`,
    );
  }

  return response.json();
}

export const authService = {
  async getConfig(): Promise<AuthConfig> {
    return apiFetch<AuthConfig>('/auth/config');
  },
};

export const namespaceService = {
  async list(): Promise<string[]> {
    const response = await apiFetch<{ namespaces: string[] }>(
      '/namespaces?enabled_only=true',
    );
    return response.namespaces;
  },
};

export const agentService = {
  async list(namespace: string): Promise<Agent[]> {
    const response = await apiFetch<{ items: Agent[] }>(
      `/agents?namespace=${encodeURIComponent(namespace)}`,
    );
    return response.items;
  },
};

export const chatService = {
  async sendMessage(
    namespace: string,
    name: string,
    message: string,
    sessionId?: string,
  ): Promise<ChatResponse> {
    return apiFetch<ChatResponse>(
      `/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/send`,
      {
        method: 'POST',
        body: JSON.stringify({
          message,
          session_id: sessionId,
        }),
      },
    );
  },
};

export const tokenBrokerService = {
  async createSession(redirectUrl: string): Promise<boolean> {
    try {
      console.log('[TokenBroker] Creating session with redirect URL:', redirectUrl);
      const token = tokenGetter ? await tokenGetter() : null;
      console.log('[TokenBroker] Token available:', !!token);
      
      if (token) {
        // Decode and log token claims for debugging
        try {
          const parts = token.split('.');
          if (parts.length === 3) {
            const payload = JSON.parse(atob(parts[1]));
            console.log('[TokenBroker] Token claims:', payload);
            console.log('[TokenBroker] Has sub claim:', !!payload.sub);
            console.log('[TokenBroker] Has aud claim:', !!payload.aud);
          }
        } catch (e) {
          console.error('[TokenBroker] Failed to decode token:', e);
        }
      }
      
      const response = await fetch(`${API_BASE}/token-broker/session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ redirect_url: redirectUrl }),
      });
      
      console.log('[TokenBroker] Session creation response status:', response.status);
      if (response.status !== 201) {
        const text = await response.text();
        console.error('[TokenBroker] Session creation failed:', text);
      }
      return response.status === 201;
    } catch (error) {
      console.error('[TokenBroker] Session creation error:', error);
      return false;
    }
  },

  async pollEvents(): Promise<TokenBrokerEvent | null> {
    const headers: Record<string, string> = {};
    if (tokenGetter) {
      const token = await tokenGetter();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}/token-broker/ui-events`, {
      headers,
    });
    if (response.status === 204) return null;
    if (!response.ok) throw new Error(`Poll failed: ${response.status}`);
    return response.json();
  },

  async endSession(): Promise<void> {
    const headers: Record<string, string> = {};
    if (tokenGetter) {
      const token = await tokenGetter();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    await fetch(`${API_BASE}/token-broker/session`, {
      method: 'DELETE',
      headers,
    }).catch(() => {});
  },
};
