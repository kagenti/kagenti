// Package config handles kagenti-admin configuration.
package config

import (
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

const (
	configDir  = ".config/kagenti"
	configFile = "admin.yaml"
)

// Config holds the admin TUI configuration.
type Config struct {
	DefaultPlatform string      `yaml:"default_platform,omitempty"`
	LastTest        *TestResult `yaml:"last_test,omitempty"`
}

// TestResult records the outcome of the last test run.
type TestResult struct {
	Platform  string     `yaml:"platform"`
	Passed    bool       `yaml:"passed"`
	Timestamp string     `yaml:"timestamp"`
	Deps      []DepBuild `yaml:"deps,omitempty"`
}

// DepBuild tracks a dependency that was built from source.
type DepBuild struct {
	Repo   string `yaml:"repo"`
	Ref    string `yaml:"ref"`
	Commit string `yaml:"commit"`
}

func configPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, configDir, configFile)
}

// Load reads the config file, falling back to defaults.
func Load() *Config {
	cfg := &Config{}
	if data, err := os.ReadFile(configPath()); err == nil {
		yaml.Unmarshal(data, cfg)
	}
	return cfg
}

// Save persists the config.
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
