// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package config

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/discover"
	"gopkg.in/yaml.v3"
)

const (
	defaultDir  = "kagenti"
	configFile  = "config.yaml"
	tokenFile   = "token"
	envBackend     = "KAGENTI_BACKEND_URL"
	envDiscovery   = "KAGENTI_BACKEND_DISCOVERY"
	envBackendNS   = "KAGENTI_BACKEND_NAMESPACE"
	envToken          = "KAGENTI_TOKEN"
	envTokenFile      = "KAGENTI_TOKEN_PATH"
	envKeycloakURL    = "KAGENTI_KEYCLOAK_URL"
	envKeycloakRealm  = "KAGENTI_KEYCLOAK_REALM"
	envOIDCClientID   = "KAGENTI_OIDC_CLIENT_ID"
	envOIDCClientSec  = "KAGENTI_OIDC_CLIENT_SECRET"
	envOIDCLocalPort  = "KAGENTI_OIDC_LOCAL_PORT"
)

// Config holds CLI settings (backend URL and where the bearer token is stored).
type Config struct {
	BackendURL       string `yaml:"backend_url"`
	BackendDiscovery string `yaml:"backend_discovery"` // auto | route | service
	BackendNamespace string `yaml:"backend_namespace"` // default kagenti-system
	TokenPath        string `yaml:"token_path"`
	KeycloakURL      string `yaml:"keycloak_url"`       // optional; overrides CM/API discovery for IdP host
	KeycloakRealm    string `yaml:"keycloak_realm"`     // with keycloak_url (default kagenti)
	OIDCClientID     string `yaml:"oidc_client_id"`     // default kagenti-ui
	OIDCLocalPort    int    `yaml:"oidc_local_port"`    // localhost callback port (default 8250)
}

// Dir returns the config directory (XDG_CONFIG_HOME/kagenti or ~/.config/kagenti).
func Dir() (string, error) {
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, defaultDir), nil
}

// DefaultTokenPath is used when token_path is unset in config.
func DefaultTokenPath() (string, error) {
	d, err := Dir()
	if err != nil {
		return "", err
	}
	return filepath.Join(d, tokenFile), nil
}

// Load reads config.yaml. Missing file yields zero Config (not an error).
func Load() (Config, error) {
	dir, err := Dir()
	if err != nil {
		return Config{}, err
	}
	path := filepath.Join(dir, configFile)
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Config{}, nil
		}
		return Config{}, fmt.Errorf("read config: %w", err)
	}
	var c Config
	if err := yaml.Unmarshal(data, &c); err != nil {
		return Config{}, fmt.Errorf("parse config: %w", err)
	}
	return c, nil
}

// EffectiveBackendURL returns backend URL from env or config.
func (c Config) EffectiveBackendURL() string {
	if v := strings.TrimSpace(os.Getenv(envBackend)); v != "" {
		return strings.TrimRight(v, "/")
	}
	return strings.TrimRight(strings.TrimSpace(c.BackendURL), "/")
}

// ResolveBackendURL returns explicit URL from env/config, or discovers via kubectl/oc
// (Route kagenti-api, then Service kagenti-backend in kagenti-system by default).
// discoveryFlagOverride is non-empty from --backend-discovery (auto|route|service).
func (c Config) ResolveBackendURL(ctx context.Context, discoveryFlagOverride string) (string, error) {
	if u := c.EffectiveBackendURL(); u != "" {
		return u, nil
	}
	modeStr := c.backendDiscoveryMode()
	if strings.TrimSpace(discoveryFlagOverride) != "" {
		modeStr = strings.TrimSpace(discoveryFlagOverride)
	}
	return discover.Resolve(ctx, discover.Options{
		Mode:      discover.ParseMode(modeStr),
		Namespace: c.backendNamespaceValue(),
		Kubectl:   strings.TrimSpace(os.Getenv("KAGENTI_KUBECTL")),
	})
}

func (c Config) backendDiscoveryMode() string {
	if v := strings.TrimSpace(os.Getenv(envDiscovery)); v != "" {
		return v
	}
	return strings.TrimSpace(c.BackendDiscovery)
}

func (c Config) backendNamespaceValue() string {
	if v := strings.TrimSpace(os.Getenv(envBackendNS)); v != "" {
		return v
	}
	if strings.TrimSpace(c.BackendNamespace) != "" {
		return c.BackendNamespace
	}
	return discover.DefaultNamespace
}

// NamespaceForClusterResources is the namespace for kagenti-ui-config and oauth secret (default kagenti-system).
func (c Config) NamespaceForClusterResources() string {
	return c.backendNamespaceValue()
}

// EffectiveTokenPath returns path to JWT file.
func (c Config) EffectiveTokenPath() (string, error) {
	if v := strings.TrimSpace(os.Getenv(envTokenFile)); v != "" {
		return expandHome(v), nil
	}
	if strings.TrimSpace(c.TokenPath) != "" {
		return expandHome(c.TokenPath), nil
	}
	return DefaultTokenPath()
}

// BearerToken returns token from KAGENTI_TOKEN env or token file contents.
func (c Config) BearerToken() (string, error) {
	if v := strings.TrimSpace(os.Getenv(envToken)); v != "" {
		return v, nil
	}
	p, err := c.EffectiveTokenPath()
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(p)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", fmt.Errorf("read token file: %w", err)
	}
	return strings.TrimSpace(string(data)), nil
}

// EffectiveKeycloakURL from env or config (optional explicit IdP base URL).
func (c Config) EffectiveKeycloakURL() string {
	if v := strings.TrimSpace(os.Getenv(envKeycloakURL)); v != "" {
		return strings.TrimRight(v, "/")
	}
	return strings.TrimRight(strings.TrimSpace(c.KeycloakURL), "/")
}

// EffectiveKeycloakRealm when using explicit keycloak_url.
func (c Config) EffectiveKeycloakRealm() string {
	if v := strings.TrimSpace(os.Getenv(envKeycloakRealm)); v != "" {
		return v
	}
	if strings.TrimSpace(c.KeycloakRealm) != "" {
		return strings.TrimSpace(c.KeycloakRealm)
	}
	return ""
}

// EffectiveOIDCClientID for browser login.
func (c Config) EffectiveOIDCClientID() string {
	if v := strings.TrimSpace(os.Getenv(envOIDCClientID)); v != "" {
		return v
	}
	if strings.TrimSpace(c.OIDCClientID) != "" {
		return strings.TrimSpace(c.OIDCClientID)
	}
	return ""
}

// OIDCCallbackPort for http://127.0.0.1:<port>/oauth/callback.
func (c Config) OIDCCallbackPort() int {
	if v := strings.TrimSpace(os.Getenv(envOIDCLocalPort)); v != "" {
		if p, err := strconv.Atoi(v); err == nil && p > 0 {
			return p
		}
	}
	if c.OIDCLocalPort > 0 {
		return c.OIDCLocalPort
	}
	return 8250
}

// OIDCClientSecret for confidential Keycloak clients (optional).
func (c Config) OIDCClientSecret() string {
	return strings.TrimSpace(os.Getenv(envOIDCClientSec))
}

// WriteTokenFile stores the access token for subsequent commands.
func (c Config) WriteTokenFile(token string) error {
	p, err := c.EffectiveTokenPath()
	if err != nil {
		return err
	}
	dir := filepath.Dir(p)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	return os.WriteFile(p, []byte(strings.TrimSpace(token)+"\n"), 0600)
}

func expandHome(p string) string {
	if len(p) >= 2 && p[0] == '~' && (p[1] == '/' || p[1] == filepath.Separator) {
		home, err := os.UserHomeDir()
		if err != nil {
			return p
		}
		return filepath.Join(home, p[2:])
	}
	return p
}


// EnvTokenName is the environment variable that can hold the raw JWT (overrides token file).
func EnvTokenName() string { return envToken }

// EnvOIDCClientSecretName for confidential clients.
func EnvOIDCClientSecretName() string { return envOIDCClientSec }
