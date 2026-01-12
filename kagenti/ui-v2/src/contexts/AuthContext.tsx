// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

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

import { setTokenGetter } from '@/services/api';

// API base URL for fetching auth config
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

// Auth config response from backend
interface AuthConfigResponse {
  enabled: boolean;
  keycloak_url?: string;
  realm?: string;
  client_id?: string;
  redirect_uri?: string;
}

export interface User {
  username: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  roles: string[];
}

export interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  isEnabled: boolean;
  user: User | null;
  token: string | null;
  error: string | null;
  login: () => void;
  logout: () => void;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isEnabled, setIsEnabled] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Keep keycloak instance in a ref so it persists across renders
  const keycloakRef = useRef<Keycloak | null>(null);

  // Extract user info from Keycloak token
  const extractUserInfo = useCallback(
    (keycloak: Keycloak, clientId: string): User | null => {
      if (!keycloak.tokenParsed) {
        return null;
      }

      const tokenParsed = keycloak.tokenParsed as {
        preferred_username?: string;
        email?: string;
        given_name?: string;
        family_name?: string;
        realm_access?: { roles?: string[] };
        resource_access?: Record<string, { roles?: string[] }>;
      };

      // Get roles from realm and client access
      const realmRoles = tokenParsed.realm_access?.roles || [];
      const clientRoles = tokenParsed.resource_access?.[clientId]?.roles || [];

      return {
        username: tokenParsed.preferred_username || 'unknown',
        email: tokenParsed.email,
        firstName: tokenParsed.given_name,
        lastName: tokenParsed.family_name,
        roles: [...realmRoles, ...clientRoles],
      };
    },
    []
  );

  // Fetch auth config from backend and initialize Keycloak
  useEffect(() => {
    let refreshInterval: ReturnType<typeof setInterval> | null = null;

    const initAuth = async () => {
      try {
        // Fetch auth config from backend
        const response = await fetch(`${API_BASE_URL}/auth/config`);
        if (!response.ok) {
          throw new Error('Failed to fetch auth config');
        }

        const config: AuthConfigResponse = await response.json();
        console.log('Auth config received:', config);
        setIsEnabled(config.enabled);

        if (!config.enabled) {
          // Auth disabled - allow access without authentication
          // User remains unauthenticated but can access the app
          console.log('Auth is disabled');
          setIsAuthenticated(false);
          setUser(null);
          setIsLoading(false);
          return;
        }

        console.log('Auth is enabled, initializing Keycloak...');

        // Auth enabled - initialize Keycloak with config from backend
        if (!config.keycloak_url || !config.realm || !config.client_id) {
          console.error('Incomplete auth config from backend:', config);
          setIsLoading(false);
          return;
        }

        const keycloak = new Keycloak({
          url: config.keycloak_url,
          realm: config.realm,
          clientId: config.client_id,
        });
        keycloakRef.current = keycloak;

        // Add error handlers before init
        keycloak.onAuthError = (errorData) => {
          const errorMsg = `Keycloak auth error: ${JSON.stringify(errorData)}`;
          console.error(errorMsg);
          setError(errorMsg);
        };

        keycloak.onAuthRefreshError = () => {
          const errorMsg = 'Keycloak token refresh failed';
          console.error(errorMsg);
          setError(errorMsg);
        };

        keycloak.onTokenExpired = () => {
          console.warn('Keycloak token expired, attempting refresh');
          keycloak.updateToken(30).catch((err) => {
            console.error('Token refresh on expiry failed:', err);
            setError('Session expired. Please login again.');
          });
        };

        console.log('Initializing Keycloak with config:', {
          url: config.keycloak_url,
          realm: config.realm,
          clientId: config.client_id,
          redirectUri: config.redirect_uri,
          currentUrl: window.location.href,
        });

        // Try to init without silent check SSO to avoid iframe timeout issues
        const authenticated = await keycloak.init({
          onLoad: 'check-sso',
          checkLoginIframe: false, // Disable iframe check completely
          pkceMethod: 'S256',
          enableLogging: true, // Enable Keycloak adapter logging
          flow: 'standard', // Use standard authorization code flow
          // Use redirect_uri from config if provided
          ...(config.redirect_uri && { redirectUri: config.redirect_uri }),
        }).catch((initError) => {
          console.error('Keycloak init rejected with error:', initError);

          // Handle case where initError is undefined (e.g., 401 on token endpoint)
          if (initError === undefined) {
            console.error('Keycloak init failed with undefined error - likely a 401 on token endpoint');
            console.error('This usually means:');
            console.error('  1. Client secret mismatch between UI config and Keycloak');
            console.error('  2. Client not configured for the correct access type in Keycloak');
            console.error('  3. Redirect URI mismatch');
            throw new Error('Keycloak authentication failed. Check Keycloak client configuration.');
          }

          console.error('Error details:', {
            message: initError?.message,
            error: initError?.error,
            error_description: initError?.error_description,
            fullError: JSON.stringify(initError, null, 2),
          });

          // If it's a timeout on silent check, it's not critical - just means no existing session
          if (initError?.error && typeof initError.error === 'string' && initError.error.toLowerCase().includes('iframe')) {
            console.warn('Silent SSO check failed (iframe timeout), continuing without existing session');
            return false; // Return false for authenticated, don't throw
          }

          throw initError;
        });

        console.log('Keycloak initialized, authenticated:', authenticated);
        console.log('Keycloak token:', keycloak.token ? 'present' : 'none');
        console.log('Keycloak refresh token:', keycloak.refreshToken ? 'present' : 'none');
        
        setIsAuthenticated(authenticated);
        setError(null); // Clear any previous errors

        if (authenticated) {
          const accessToken = keycloak.token || null;
          setToken(accessToken);
          setUser(extractUserInfo(keycloak, config.client_id));
          
          // Store token in sessionStorage for persistence
          if (accessToken) {
            sessionStorage.setItem('kagenti_access_token', accessToken);
          }
        }

        // Set up token refresh
        refreshInterval = setInterval(() => {
          if (keycloak.authenticated) {
            keycloak
              .updateToken(60) // Refresh if token expires in 60 seconds
              .then((refreshed) => {
                if (refreshed) {
                  const newToken = keycloak.token || null;
                  setToken(newToken);
                  // Update sessionStorage with new token
                  if (newToken) {
                    sessionStorage.setItem('kagenti_access_token', newToken);
                  }
                  console.debug('Token refreshed');
                }
              })
              .catch(() => {
                console.warn('Token refresh failed, logging out');
                keycloak.logout();
              });
          }
        }, 30000); // Check every 30 seconds
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        console.error('Auth initialization failed:', error);
        console.error('Error details:', {
          message: errorMsg,
          stack: error instanceof Error ? error.stack : undefined,
          type: error instanceof Error ? error.constructor.name : typeof error,
          error: (error as any).error,
          error_description: (error as any).error_description,
          fullError: error,
        });
        
        // Create user-friendly error message
        let userErrorMsg = `Authentication failed: ${errorMsg}`;
        if ((error as any).error === 'invalid_grant') {
          userErrorMsg = 'Authentication failed: Invalid authorization code. Please try again.';
        } else if ((error as any).error === 'unauthorized_client') {
          userErrorMsg = 'Authentication failed: Client not authorized. Check Keycloak configuration.';
        } else if ((error as any).error_description) {
          userErrorMsg = `Authentication failed: ${(error as any).error_description}`;
        }
        
        // On error, keep auth enabled so user can still try to login
        // (the Sign In button should still be visible)
        // setIsEnabled remains at its last value (should be true if config.enabled was true)
        setError(userErrorMsg);
        setIsAuthenticated(false);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();

    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, [extractUserInfo]);

  // Login function
  const login = useCallback(() => {
    if (!isEnabled || !keycloakRef.current) {
      console.error('Cannot login: isEnabled=', isEnabled, 'keycloak=', !!keycloakRef.current);
      return;
    }
    console.log('Initiating login redirect...');
    setError(null); // Clear any previous errors
    keycloakRef.current.login().catch((err) => {
      const errorMsg = `Login failed: ${err.message || err}`;
      console.error(errorMsg, err);
      setError(errorMsg);
    });
  }, [isEnabled]);

  // Logout function
  const logout = useCallback(() => {
    if (!isEnabled || !keycloakRef.current) return;
    // Clear token from sessionStorage
    sessionStorage.removeItem('kagenti_access_token');
    keycloakRef.current.logout({
      redirectUri: window.location.origin,
    });
  }, [isEnabled]);

  // Get current token (with refresh if needed)
  const getToken = useCallback(async (): Promise<string | null> => {
    if (!isEnabled) {
      // Auth disabled - no token available
      return null;
    }

    const keycloak = keycloakRef.current;
    if (!keycloak || !keycloak.authenticated) {
      // Try to restore from sessionStorage if available
      const storedToken = sessionStorage.getItem('kagenti_access_token');
      return storedToken || null;
    }

    try {
      const refreshed = await keycloak.updateToken(30);
      const currentToken = keycloak.token || null;
      
      // Update sessionStorage if token was refreshed
      if (refreshed && currentToken) {
        sessionStorage.setItem('kagenti_access_token', currentToken);
      }
      
      return currentToken;
    } catch {
      console.error('Failed to refresh token');
      // Try to return stored token as fallback
      const storedToken = sessionStorage.getItem('kagenti_access_token');
      return storedToken || null;
    }
  }, [isEnabled]);

  // Register token getter with API service
  useEffect(() => {
    setTokenGetter(getToken);
  }, [getToken]);

  const value = useMemo(
    () => ({
      isAuthenticated,
      isLoading,
      isEnabled,
      user,
      token,
      error,
      login,
      logout,
      getToken,
    }),
    [isAuthenticated, isLoading, isEnabled, user, token, error, login, logout, getToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// Hook to use auth context
export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
