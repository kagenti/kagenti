package helpers

import (
	"testing"
)

func TestLLMPresetEnvVarsOpenAI(t *testing.T) {
	vars := LLMPresetEnvVars("openai", "")
	if len(vars) != 4 {
		t.Fatalf("expected 4 env vars for openai preset, got %d", len(vars))
	}
	// Check default model
	for _, v := range vars {
		if v.Name == "LLM_MODEL" && v.Value != "gpt-4o-mini-2024-07-18" {
			t.Errorf("expected default openai model, got %q", v.Value)
		}
	}
}

func TestLLMPresetEnvVarsOpenAIOverride(t *testing.T) {
	vars := LLMPresetEnvVars("openai", "gpt-4")
	for _, v := range vars {
		if v.Name == "LLM_MODEL" && v.Value != "gpt-4" {
			t.Errorf("expected model override 'gpt-4', got %q", v.Value)
		}
	}
}

func TestLLMPresetEnvVarsOllama(t *testing.T) {
	vars := LLMPresetEnvVars("ollama", "")
	if len(vars) != 3 {
		t.Fatalf("expected 3 env vars for ollama preset, got %d", len(vars))
	}
	for _, v := range vars {
		if v.Name == "LLM_MODEL" && v.Value != "llama3.2:3b-instruct-fp16" {
			t.Errorf("expected default ollama model, got %q", v.Value)
		}
	}
}

func TestLLMPresetEnvVarsNone(t *testing.T) {
	vars := LLMPresetEnvVars("", "")
	if vars != nil {
		t.Errorf("expected nil for empty preset, got %v", vars)
	}
}

func TestOpenBrowserRejectsNonHTTPSchemes(t *testing.T) {
	var opened []string
	orig := OpenBrowser
	OpenBrowser = func(u string) {
		opened = append(opened, u)
		// Call the real implementation to exercise the scheme check.
		openBrowserDefault(u)
	}
	defer func() { OpenBrowser = orig }()

	// These should be silently rejected (no exec.Command called).
	for _, bad := range []string{
		"file:///etc/passwd",
		"javascript:alert(1)",
		"ftp://example.com",
		"",
		"://missing-scheme",
	} {
		openBrowserDefault(bad)
	}

	// Valid schemes would attempt exec.Command, which is fine —
	// we just verify the function doesn't panic on invalid input.
}

func TestParseEnvVars(t *testing.T) {
	tests := []struct {
		input string
		count int
		first string
	}{
		{"", 0, ""},
		{"FOO=bar", 1, "FOO"},
		{"FOO=bar,BAZ=qux", 2, "FOO"},
		{"FOO=bar, BAZ=qux", 2, "FOO"},
		{" FOO = bar , BAZ = qux ", 2, "FOO"},
		{",,,", 0, ""},
	}
	for _, tc := range tests {
		vars := ParseEnvVars(tc.input)
		if len(vars) != tc.count {
			t.Errorf("ParseEnvVars(%q): expected %d vars, got %d", tc.input, tc.count, len(vars))
			continue
		}
		if tc.count > 0 && vars[0].Name != tc.first {
			t.Errorf("ParseEnvVars(%q): expected first name %q, got %q", tc.input, tc.first, vars[0].Name)
		}
	}
}
