// Package helpers provides shared utility functions used by both the
// interactive TUI views and the non-interactive CLI commands.
package helpers

import (
	"net/url"
	"os/exec"
	"runtime"
	"strings"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
)

// LLMPresetEnvVars returns environment variables for a given LLM environment preset.
func LLMPresetEnvVars(preset, modelOverride string) []api.EnvVar {
	secretRef := func(secretName, key string) *api.EnvVarSource {
		return &api.EnvVarSource{
			SecretKeyRef: &api.SecretKeyRef{Name: secretName, Key: key},
		}
	}

	switch preset {
	case "openai":
		model := "gpt-4o-mini-2024-07-18"
		if modelOverride != "" {
			model = modelOverride
		}
		return []api.EnvVar{
			{Name: "OPENAI_API_KEY", ValueFrom: secretRef("openai-secret", "apikey")},
			{Name: "LLM_API_KEY", ValueFrom: secretRef("openai-secret", "apikey")},
			{Name: "LLM_API_BASE", Value: "https://api.openai.com/v1"},
			{Name: "LLM_MODEL", Value: model},
		}
	case "ollama":
		model := "llama3.2:3b-instruct-fp16"
		if modelOverride != "" {
			model = modelOverride
		}
		return []api.EnvVar{
			{Name: "LLM_API_BASE", Value: "http://host.docker.internal:11434/v1"},
			{Name: "LLM_API_KEY", Value: "dummy"},
			{Name: "LLM_MODEL", Value: model},
		}
	default:
		return nil
	}
}

// ParseEnvVars parses comma-separated KEY=VALUE pairs into env vars.
func ParseEnvVars(raw string) []api.EnvVar {
	if raw == "" {
		return nil
	}
	var envVars []api.EnvVar
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		parts := strings.SplitN(pair, "=", 2)
		if len(parts) == 2 {
			envVars = append(envVars, api.EnvVar{
				Name:  strings.TrimSpace(parts[0]),
				Value: strings.TrimSpace(parts[1]),
			})
		}
	}
	return envVars
}

// OpenBrowser attempts to open a URL in the default browser.
// It is a variable so tests can replace it with a no-op.
var OpenBrowser = openBrowserDefault

func openBrowserDefault(rawURL string) {
	parsed, err := url.Parse(rawURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return
	}
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", rawURL)
	case "linux":
		cmd = exec.Command("xdg-open", rawURL)
	default:
		return
	}
	_ = cmd.Start()
}
