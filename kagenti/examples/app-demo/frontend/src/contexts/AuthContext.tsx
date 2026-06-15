import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
  useRef,
} from 'react';
import Keycloak from 'keycloak-js';

import { setTokenGetter, tokenBrokerService } from '@/services/api';
import type { AuthConfig, User } from '@/types';

const API_BASE = '/api/v1';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  isEnabled: boolean;
  tokenBrokerEnabled: boolean;
  user: User | null;
  login: () => void;
  logout: () => void;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isEnabled, setIsEnabled] = useState(false);
  const [tokenBrokerEnabled, setTokenBrokerEnabled] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const keycloakRef = useRef<Keycloak | null>(null);

  const extractUser = useCallback((kc: Keycloak): User | null => {
    if (!kc.tokenParsed) return null;
    const tp = kc.tokenParsed as Record<string, unknown>;
    return {
      username: (tp.preferred_username as string) || 'user',
      email: tp.email as string | undefined,
      firstName: tp.given_name as string | undefined,
      lastName: tp.family_name as string | undefined,
    };
  }, []);

  const getToken = useCallback(async (): Promise<string | null> => {
    const kc = keycloakRef.current;
    if (!kc?.authenticated) return null;
    try {
      await kc.updateToken(30);
      return kc.token ?? null;
    } catch (error) {
      // Token refresh failed - trigger re-login
      console.error('[AuthContext] Token refresh failed, triggering re-login:', error);
      setIsAuthenticated(false);
      setUser(null);
      // Trigger login to get fresh tokens
      kc.login({
        redirectUri: window.location.href,
      });
      return null;
    }
  }, []);

  useEffect(() => {
    let refreshInterval: ReturnType<typeof setInterval>;

    async function init() {
      try {
        const resp = await fetch(`${API_BASE}/auth/config`);
        const config: AuthConfig = await resp.json();
        
        console.log('[AuthContext] Auth config received:', config);
        console.log('[AuthContext] Token Broker enabled:', config.token_broker_enabled);
        setTokenBrokerEnabled(config.token_broker_enabled ?? false);

        if (!config.enabled || !config.keycloak_url) {
          setIsEnabled(false);
          setIsLoading(false);
          return;
        }

        setIsEnabled(true);

        const kc = new Keycloak({
          url: config.keycloak_url,
          realm: config.realm || 'kagenti',
          clientId: config.client_id || 'app-demo',
        });

        keycloakRef.current = kc;

        const authenticated = await kc.init({
          onLoad: 'check-sso',
          pkceMethod: 'S256',
          checkLoginIframe: false,
          redirectUri: window.location.origin + '/',
        });

        if (authenticated && kc.token) {
          setIsAuthenticated(true);
          setUser(extractUser(kc));
          setTokenGetter(() => getToken());

          // Create Token Broker session after successful login
          if (config.token_broker_enabled) {
            console.log('[AuthContext] Creating Token Broker session after login...');
            console.log('[AuthContext] Token parsed:', kc.tokenParsed);
            
            // Ensure token is fresh and has all required claims
            try {
              await kc.updateToken(5);
              console.log('[AuthContext] Token refreshed, creating session...');
            } catch (err) {
              console.error('[AuthContext] Token refresh failed:', err);
            }
            
            const sessionOk = await tokenBrokerService.createSession(
              window.location.origin + '/oauth-complete.html'
            );
            console.log('[AuthContext] Token Broker session created:', sessionOk);
          }

          refreshInterval = setInterval(async () => {
            try {
              const refreshed = await kc.updateToken(60);
              if (refreshed) {
                setUser(extractUser(kc));
              }
            } catch {
              setIsAuthenticated(false);
              setUser(null);
            }
          }, 30000);
        }
      } catch {
        // auth init failed — continue as guest
      } finally {
        setIsLoading(false);
      }
    }

    init();
    return () => clearInterval(refreshInterval);
  }, [extractUser, getToken]);

  const login = useCallback(() => {
    keycloakRef.current?.login({
      redirectUri: window.location.origin + '/',
    });
  }, []);

  const logout = useCallback(async () => {
    // End Token Broker session before logout
    if (tokenBrokerEnabled) {
      console.log('[AuthContext] Ending Token Broker session on logout...');
      await tokenBrokerService.endSession();
    }
    
    keycloakRef.current?.logout({
      redirectUri: window.location.origin + '/',
    });
  }, [tokenBrokerEnabled]);

  const value = useMemo(
    () => ({
      isAuthenticated,
      isLoading,
      isEnabled,
      tokenBrokerEnabled,
      user,
      login,
      logout,
      getToken,
    }),
    [isAuthenticated, isLoading, isEnabled, tokenBrokerEnabled, user, login, logout, getToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
