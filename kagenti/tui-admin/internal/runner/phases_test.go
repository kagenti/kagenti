package runner

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestPlatformPhases(t *testing.T) {
	t.Parallel()
	phases := PlatformPhases("kind")
	if len(phases) == 0 {
		t.Fatal("expected at least one phase")
	}

	// Verify expected phases exist
	names := make(map[string]bool)
	for _, p := range phases {
		names[p.Name] = true
		if p.Description == "" {
			t.Errorf("phase %q has empty description", p.Name)
		}
		if len(p.Scripts) == 0 {
			t.Errorf("phase %q has no scripts", p.Name)
		}
	}

	expected := []string{"secrets", "install", "wait-platform", "deploy-agents", "e2e"}
	for _, name := range expected {
		if !names[name] {
			t.Errorf("missing expected phase: %s", name)
		}
	}
}

func TestRunPhaseScriptNotFound(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	r := &Runner{Stdout: &buf, Stderr: &buf}

	phase := Phase{
		Name:    "test",
		Scripts: []string{"nonexistent-script.sh"},
	}

	result := r.RunPhase(context.Background(), t.TempDir(), phase, nil)
	if result.Error == nil {
		t.Error("expected error for missing script")
	}
}

func TestRunPhaseSuccess(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()

	// Create a simple script
	script := filepath.Join(dir, "test.sh")
	os.WriteFile(script, []byte("#!/bin/sh\necho ok"), 0o755)

	var buf bytes.Buffer
	r := &Runner{Stdout: &buf, Stderr: &buf}

	phase := Phase{
		Name:    "test",
		Scripts: []string{"test.sh"},
	}

	result := r.RunPhase(context.Background(), dir, phase, nil)
	if result.Error != nil {
		t.Errorf("unexpected error: %v", result.Error)
	}
	if result.Duration == 0 {
		t.Error("expected non-zero duration")
	}
}

func TestRunPhasesStopsOnError(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()

	// Create a failing script and a succeeding one
	os.WriteFile(filepath.Join(dir, "fail.sh"), []byte("#!/bin/sh\nexit 1"), 0o755)
	os.WriteFile(filepath.Join(dir, "pass.sh"), []byte("#!/bin/sh\necho ok"), 0o755)

	var buf bytes.Buffer
	r := &Runner{Stdout: &buf, Stderr: &buf}

	phases := []Phase{
		{Name: "pass", Scripts: []string{"pass.sh"}},
		{Name: "fail", Scripts: []string{"fail.sh"}},
		{Name: "never", Scripts: []string{"pass.sh"}}, // should not run
	}

	results := r.RunPhases(context.Background(), dir, phases, nil)
	if len(results) != 2 {
		t.Errorf("expected 2 results (stop on failure), got %d", len(results))
	}
	if results[0].Error != nil {
		t.Error("first phase should pass")
	}
	if results[1].Error == nil {
		t.Error("second phase should fail")
	}
}

func TestFindRepoRoot(t *testing.T) {
	t.Parallel()
	root, err := FindRepoRoot()
	if err != nil {
		t.Skipf("not in a git repo: %v", err)
	}
	// Verify .git exists at root
	if _, err := os.Stat(filepath.Join(root, ".git")); err != nil {
		t.Errorf("expected .git at repo root %s: %v", root, err)
	}
}
