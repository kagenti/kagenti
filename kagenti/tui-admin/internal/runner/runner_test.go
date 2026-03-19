package runner

import (
	"bytes"
	"context"
	"testing"
)

func TestRunnerDryRun(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	r := &Runner{Stdout: &buf, Stderr: &buf, DryRun: true}

	result, err := r.Run(context.Background(), "echo", "hello")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Stdout != "" {
		t.Errorf("expected empty stdout in dry-run, got %q", result.Stdout)
	}
	if !bytes.Contains(buf.Bytes(), []byte("[dry-run]")) {
		t.Errorf("expected dry-run message, got %q", buf.String())
	}
}

func TestRunnerEcho(t *testing.T) {
	t.Parallel()
	var stdout, stderr bytes.Buffer
	r := &Runner{Stdout: &stdout, Stderr: &stderr}

	result, err := r.Run(context.Background(), "echo", "hello")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Stdout != "hello\n" {
		t.Errorf("expected 'hello\\n', got %q", result.Stdout)
	}
}

func TestRunSilent(t *testing.T) {
	t.Parallel()
	var stdout bytes.Buffer
	r := &Runner{Stdout: &stdout, Stderr: &stdout}

	result, err := r.RunSilent(context.Background(), "echo", "silent")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Stdout != "silent" {
		t.Errorf("expected 'silent', got %q", result.Stdout)
	}
	// Stdout should NOT have been written to (silent mode)
	if stdout.Len() > 0 {
		t.Errorf("expected no stdout output in silent mode, got %q", stdout.String())
	}
}

func TestRunnerFailingCommand(t *testing.T) {
	t.Parallel()
	r := New()
	_, err := r.RunSilent(context.Background(), "false")
	if err == nil {
		t.Fatal("expected error for failing command")
	}
}

func TestCommandExists(t *testing.T) {
	t.Parallel()
	if !CommandExists("echo") {
		t.Error("echo should exist")
	}
	if CommandExists("nonexistent-binary-xyz-12345") {
		t.Error("nonexistent binary should not exist")
	}
}
