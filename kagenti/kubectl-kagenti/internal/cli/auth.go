// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/authoidc"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/config"
	"github.com/spf13/cobra"
)

func authCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "auth",
		Short: "Authenticate against Keycloak (browser + callback) and call the API",
	}
	c.AddCommand(authStatusCmd(), authLoginCmd(), authLogoutCmd())
	return c
}

func authStatusCmd() *cobra.Command {
	var doLogin bool
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show current user (GET /api/v1/auth/me); use --login to acquire a token via browser",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load()
			if err != nil {
				return err
			}
			base, err := cfg.ResolveBackendURL(cmd.Context(), rootBackendDiscovery)
			if err != nil {
				return err
			}
			token, err := cfg.BearerToken()
			if err != nil {
				return err
			}
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			if token == "" {
				if doLogin {
					token, err = runBrowserLogin(cmd, cfg, base)
					if err != nil {
						return err
					}
					if token == "" {
						return fmt.Errorf("login did not produce a token")
					}
				} else {
					_, _ = fmt.Fprintf(cmd.ErrOrStderr(), `Not authenticated: no bearer token.

  • kubectl kagenti auth login          — open browser, save token to your token file
  • kubectl kagenti auth status --login — same, then show user

  • Or set %s / token file manually.

`, config.EnvTokenName())
					return nil
				}
			}
			u, code, err := client.GetMe(base, token)
			if doLogin && err != nil && code == http.StatusUnauthorized {
				_, _ = fmt.Fprintln(cmd.ErrOrStderr(), "Stored token expired or invalid; opening browser to sign in again…")
				token, err = runBrowserLogin(cmd, cfg, base)
				if err != nil {
					return err
				}
				if token == "" {
					return fmt.Errorf("login did not produce a token")
				}
				u, code, err = client.GetMe(base, token)
			}
			if err != nil {
				return fmt.Errorf("auth/me failed: %w", err)
			}
			if code != 200 {
				return fmt.Errorf("unexpected status %d", code)
			}
			return writeUserInfo(cmd.OutOrStdout(), rootOutput, u)
		},
	}
	cmd.Flags().BoolVar(&doLogin, "login", false, "Browser login if there is no token or /auth/me returns 401 (expired token)")
	return cmd
}

func authLoginCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "login",
		Short: "Open browser to sign in via Keycloak; token is saved to your configured token file",
		Long: `Resolves Keycloak using (in order):
  1) keycloak_url in config or KAGENTI_KEYCLOAK_URL
  2) ConfigMap kagenti-ui-config data KEYCLOAK_CONSOLE_URL (via kubectl/oc)
  3) GET /api/v1/auth/config on the Kagenti API
  4) Secret kagenti-ui-oauth-secret (AUTH_ENDPOINT, TOKEN_ENDPOINT, CLIENT_ID)

Uses OAuth2 authorization code with PKCE. Add this redirect URI to your Keycloak client:
  http://127.0.0.1:8250/oauth/callback
(or the port set by oidc_local_port / KAGENTI_OIDC_LOCAL_PORT)

For confidential clients, set KAGENTI_OIDC_CLIENT_SECRET.`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load()
			if err != nil {
				return err
			}
			base, err := cfg.ResolveBackendURL(cmd.Context(), rootBackendDiscovery)
			if err != nil {
				return err
			}
			_, err = runBrowserLogin(cmd, cfg, base)
			return err
		},
	}
}

// runBrowserLogin opens the browser OAuth flow and returns the new access token
// (also written to the token file). Use the return value for API calls so a stale
// KAGENTI_TOKEN env does not override the fresh token in the same invocation.
func runBrowserLogin(cmd *cobra.Command, cfg config.Config, backendBase string) (accessToken string, err error) {
	_, _ = fmt.Fprintln(cmd.ErrOrStderr(), "Opening browser for Keycloak login…")
	ep, err := authoidc.Resolve(cmd.Context(), backendBase,
		cfg.EffectiveKeycloakURL(), cfg.EffectiveKeycloakRealm(), cfg.EffectiveOIDCClientID(),
		cfg.NamespaceForClusterResources(), os.Getenv("KAGENTI_KUBECTL"))
	if err != nil {
		return "", err
	}
	if sec := cfg.OIDCClientSecret(); sec != "" {
		ep.ClientSecret = sec
	}
	tok, err := authoidc.BrowserLogin(cmd.Context(), ep, cfg.OIDCCallbackPort())
	if err != nil {
		return "", err
	}
	if err := cfg.WriteTokenFile(tok); err != nil {
		return "", fmt.Errorf("save token: %w", err)
	}
	p, _ := cfg.EffectiveTokenPath()
	_, _ = fmt.Fprintf(cmd.ErrOrStderr(), "Logged in. Token saved to %s\n", p)
	return strings.TrimSpace(tok), nil
}

func authLogoutCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "logout",
		Short: "Remove the saved token file",
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := config.Load()
			if err != nil {
				return err
			}
			p, err := cfg.EffectiveTokenPath()
			if err != nil {
				return err
			}
			if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
				return err
			}
			_, _ = fmt.Fprintln(cmd.OutOrStderr(), "Token file removed.")
			return nil
		},
	}
}
