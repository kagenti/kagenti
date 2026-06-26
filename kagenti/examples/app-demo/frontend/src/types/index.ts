export interface Agent {
  name: string;
  namespace: string;
  description: string;
  status: string;
  labels: {
    protocol?: string[];
    framework?: string;
    type?: string;
  };
  workloadType: string;
  createdAt: string;
}

export interface ChatResponse {
  content: string;
  session_id: string;
  is_complete: boolean;
}

export interface AuthConfig {
  enabled: boolean;
  keycloak_url?: string;
  realm?: string;
  client_id?: string;
  token_broker_enabled?: boolean;
}

export interface TokenBrokerEvent {
  type: string;
  auth_url?: string;
  message?: string;
  code?: string;
}

export interface User {
  username: string;
  email?: string;
  firstName?: string;
  lastName?: string;
}
