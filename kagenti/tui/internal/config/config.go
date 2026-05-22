// Package config handles configuration resolution from file, env, and flags.
package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

const (
	defaultURL       = "http://kagenti-api.localtest.me:8080"
	defaultNamespace = "team1"
	configDir        = ".config/kagenti"
	configFile       = "tui.yaml"
)

// Config holds the TUI configuration.
type Config struct {
	URL          string `yaml:"url"`
	Token        string `yaml:"token"`
	RefreshToken string `yaml:"refresh_token,omitempty"`
	Namespace    string `yaml:"namespace"`
	KeycloakURL  string `yaml:"keycloak_url,omitempty"`
	Realm        string `yaml:"realm,omitempty"`
	ClientID     string `yaml:"client_id,omitempty"`
}

// configPath returns the full path to the config file.
func configPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, configDir, configFile)
}

// Load resolves config: defaults → file → env → flags.
// Flag values should be passed in; empty string means "not set".
func Load(flagURL, flagToken, flagNamespace string) *Config {
	cfg := &Config{
		URL:       defaultURL,
		Namespace: defaultNamespace,
	}

	// Layer 1: config file (fall back to defaults on parse error)
	if data, err := os.ReadFile(configPath()); err == nil {
		if yamlErr := yaml.Unmarshal(data, cfg); yamlErr != nil {
			fmt.Fprintf(os.Stderr, "Warning: failed to parse %s: %v (using defaults)\n", configPath(), yamlErr)
		}
	}

	// Layer 2: environment variables
	if v := os.Getenv("KAGENTI_URL"); v != "" {
		cfg.URL = v
	}
	if v := os.Getenv("KAGENTI_TOKEN"); v != "" {
		cfg.Token = v
	}
	if v := os.Getenv("KAGENTI_NAMESPACE"); v != "" {
		cfg.Namespace = v
	}

	// Layer 3: CLI flags (highest priority)
	if flagURL != "" {
		cfg.URL = flagURL
	}
	if flagToken != "" {
		cfg.Token = flagToken
	}
	if flagNamespace != "" {
		cfg.Namespace = flagNamespace
	}

	return cfg
}

// Save persists the config to the file.
func (c *Config) Save() error {
	p := configPath()
	if p == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return err
	}
	data, err := yaml.Marshal(c)
	if err != nil {
		return err
	}
	return os.WriteFile(p, data, 0o600)
}
