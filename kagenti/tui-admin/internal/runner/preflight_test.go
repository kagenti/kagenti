package runner

import (
	"bytes"
	"testing"
)

func TestPlatformPreflightChecks(t *testing.T) {
	t.Parallel()

	tests := []struct {
		platform string
		required []string
	}{
		{"kind", []string{"kubectl", "helm", "kind", "docker"}},
		{"k3s", []string{"kubectl", "helm", "rdctl"}},
		{"rancher-desktop", []string{"kubectl", "helm", "rdctl"}},
		{"hypershift", []string{"kubectl", "helm", "oc", "aws"}},
	}

	for _, tt := range tests {
		t.Run(tt.platform, func(t *testing.T) {
			t.Parallel()
			checks := PlatformPreflightChecks(tt.platform)

			names := make(map[string]bool)
			for _, c := range checks {
				names[c.Name] = true
			}

			for _, req := range tt.required {
				if !names[req] {
					t.Errorf("platform %s missing check for %s", tt.platform, req)
				}
			}
		})
	}
}

func TestRunPreflightChecks(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer

	// Run checks for "kind" — kubectl should be found
	passed, results := RunPreflightChecks(&buf, "kind")

	if len(results) == 0 {
		t.Error("expected at least one result")
	}

	output := buf.String()
	if output == "" {
		t.Error("expected non-empty output")
	}

	// We can't guarantee all deps are installed, but the function should not panic
	t.Logf("Preflight passed: %v, checks: %d, output:\n%s", passed, len(results), output)
}

func TestPreflightOllamaOptional(t *testing.T) {
	t.Parallel()
	checks := PlatformPreflightChecks("kind")

	for _, c := range checks {
		if c.Name == "ollama" && c.Required {
			t.Error("ollama should be optional")
		}
	}
}

func TestDetectOS(t *testing.T) {
	t.Parallel()
	os, arch := DetectOS()
	if os == "" || arch == "" {
		t.Error("expected non-empty OS and arch")
	}
	t.Logf("OS: %s, Arch: %s", os, arch)
}

func TestFindPath(t *testing.T) {
	t.Parallel()
	// echo should be findable
	p, err := findPath("echo")
	if err != nil {
		// May not be at standard paths, that's OK
		t.Logf("echo not at standard paths: %v", err)
	} else if p == "" {
		t.Error("expected non-empty path for echo")
	}
}
