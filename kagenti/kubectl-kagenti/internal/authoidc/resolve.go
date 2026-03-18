// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package authoidc

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
)

const (
	ConfigMapName = "kagenti-ui-config"
	OAuthSecret   = "kagenti-ui-oauth-secret"
)

// Endpoints for browser login (authorization code + PKCE).
type Endpoints struct {
	AuthURL      string
	TokenURL     string
	ClientID     string
	ClientSecret string
}

// Resolve finds Keycloak/OIDC endpoints:
// 1) explicit keycloak_url (config/env)
// 2) ConfigMap kagenti-ui-config KEYCLOAK_CONSOLE_URL (kubectl)
// 3) GET /api/v1/auth/config
// 4) Secret kagenti-ui-oauth-secret
func Resolve(ctx context.Context, backendBase string, explicitURL, explicitRealm, explicitClientID string, ns, kubectl string) (*Endpoints, error) {
	bin, _ := kube.LookPath(kubectl)

	if strings.TrimSpace(explicitURL) != "" {
		realm := strings.TrimSpace(explicitRealm)
		if realm == "" {
			realm = "kagenti"
		}
		cid := strings.TrimSpace(explicitClientID)
		if cid == "" {
			cid = "kagenti-ui"
		}
		return endpointsFromBase(explicitURL, realm, cid), nil
	}
	if bin != "" {
		if console, err := kube.GetConfigMapData(ctx, bin, ns, ConfigMapName, "KEYCLOAK_CONSOLE_URL"); err == nil && strings.TrimSpace(console) != "" {
			if ep, err2 := fromConsoleURL(console, explicitClientID); err2 == nil {
				return ep, nil
			}
		}
	}
	if ac, err := client.FetchAuthConfig(ctx, backendBase); err == nil && ac != nil {
		if ac.Enabled && strings.TrimSpace(ac.KeycloakURL) != "" && strings.TrimSpace(ac.Realm) != "" && strings.TrimSpace(ac.ClientID) != "" {
			return endpointsFromBase(ac.KeycloakURL, ac.Realm, ac.ClientID), nil
		}
	}
	if bin != "" {
		if ep, err := fromOAuthSecret(ctx, bin, ns); err == nil && ep != nil {
			return ep, nil
		}
	}
	return nil, fmt.Errorf("could not resolve Keycloak: set keycloak_url in config, ensure ConfigMap %s has KEYCLOAK_CONSOLE_URL, or API %s/api/v1/auth/config exposes Keycloak (or kubectl can read %s)",
		ConfigMapName, strings.TrimRight(backendBase, "/"), OAuthSecret)
}

func endpointsFromBase(keycloakBase, realm, clientID string) *Endpoints {
	base := strings.TrimRight(strings.TrimSpace(keycloakBase), "/")
	r := strings.TrimSpace(realm)
	c := strings.TrimSpace(clientID)
	return &Endpoints{
		AuthURL:  fmt.Sprintf("%s/realms/%s/protocol/openid-connect/auth", base, r),
		TokenURL: fmt.Sprintf("%s/realms/%s/protocol/openid-connect/token", base, r),
		ClientID: c,
	}
}

func fromOAuthSecret(ctx context.Context, bin, ns string) (*Endpoints, error) {
	authEP, err := kube.GetSecretData(ctx, bin, ns, OAuthSecret, "AUTH_ENDPOINT")
	if err != nil {
		return nil, err
	}
	tokenEP, err := kube.GetSecretData(ctx, bin, ns, OAuthSecret, "TOKEN_ENDPOINT")
	if err != nil {
		return nil, err
	}
	cid, err := kube.GetSecretData(ctx, bin, ns, OAuthSecret, "CLIENT_ID")
	if err != nil {
		return nil, err
	}
	sec, _ := kube.GetSecretDataOptional(ctx, bin, ns, OAuthSecret, "CLIENT_SECRET")
	sec = strings.TrimSpace(sec)
	return &Endpoints{
		AuthURL:      strings.TrimSpace(authEP),
		TokenURL:     strings.TrimSpace(tokenEP),
		ClientID:     strings.TrimSpace(cid),
		ClientSecret: sec,
	}, nil
}

func fromConsoleURL(consoleURL, clientIDFallback string) (*Endpoints, error) {
	u, err := url.Parse(strings.TrimSpace(consoleURL))
	if err != nil || u.Host == "" {
		return nil, fmt.Errorf("invalid KEYCLOAK_CONSOLE_URL")
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	realm := ""
	for i, p := range parts {
		if p == "admin" && i+2 < len(parts) && parts[i+2] == "console" {
			realm = parts[i+1]
			break
		}
	}
	if realm == "" {
		return nil, fmt.Errorf("cannot extract realm from KEYCLOAK_CONSOLE_URL (expected .../admin/<realm>/console/...)")
	}
	u.Path = ""
	u.RawQuery = ""
	base := strings.TrimRight(u.String(), "/")
	cid := strings.TrimSpace(clientIDFallback)
	if cid == "" {
		cid = "kagenti-ui"
	}
	return endpointsFromBase(base, realm, cid), nil
}
