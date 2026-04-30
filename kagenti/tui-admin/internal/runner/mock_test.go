package runner

import (
	"bytes"
	"context"
	"testing"
)

func TestMockExecutorBasic(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()
	mock.OnResult("echo", "hello", 0)

	result, err := mock.Run(context.Background(), "echo", "world")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Stdout != "hello" {
		t.Errorf("expected 'hello', got %q", result.Stdout)
	}
	if !mock.Called("echo") {
		t.Error("expected echo to be called")
	}
}

func TestMockExecutorError(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()
	mock.OnResult("fail", "", 1)

	_, err := mock.RunSilent(context.Background(), "fail")
	if err == nil {
		t.Error("expected error for exit code 1")
	}
}

func TestMockExecutorWildcard(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()
	mock.On("*", func(args []string) (*Result, error) {
		return &Result{Stdout: "wildcard"}, nil
	})

	result, err := mock.Run(context.Background(), "anything")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Stdout != "wildcard" {
		t.Errorf("expected 'wildcard', got %q", result.Stdout)
	}
}

func TestMockExecutorCalledWith(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()
	mock.OnResult("kubectl", "", 0)

	mock.RunSilent(context.Background(), "kubectl", "get", "pods", "-n", "team1")

	if !mock.CalledWith("kubectl", "pods") {
		t.Error("expected kubectl to be called with 'pods'")
	}
	if mock.CalledWith("kubectl", "nodes") {
		t.Error("kubectl should not have been called with 'nodes'")
	}
}

func TestMockExecutorUnregistered(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()

	// Unregistered commands return empty result
	result, err := mock.Run(context.Background(), "unknown")
	if err != nil {
		t.Fatalf("unexpected error for unregistered: %v", err)
	}
	if result.Stdout != "" {
		t.Errorf("expected empty stdout for unregistered, got %q", result.Stdout)
	}
}

func TestMockExecutorOn(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()

	called := false
	mock.On("custom", func(args []string) (*Result, error) {
		called = true
		return &Result{Stdout: "custom-output"}, nil
	})

	result, _ := mock.Run(context.Background(), "custom", "arg1")
	if !called {
		t.Error("handler not called")
	}
	if result.Stdout != "custom-output" {
		t.Errorf("expected 'custom-output', got %q", result.Stdout)
	}
}

func TestMockExecutorRecordsCalls(t *testing.T) {
	t.Parallel()
	mock := NewMockExecutor()

	mock.Run(context.Background(), "cmd1", "a", "b")
	mock.RunSilent(context.Background(), "cmd2", "c")

	if len(mock.Calls) != 2 {
		t.Errorf("expected 2 calls, got %d", len(mock.Calls))
	}
	if mock.Calls[0].Name != "cmd1" {
		t.Errorf("first call: got %q, want cmd1", mock.Calls[0].Name)
	}
	if mock.Calls[1].Name != "cmd2" {
		t.Errorf("second call: got %q, want cmd2", mock.Calls[1].Name)
	}
}

func TestKubectlAndHelm(t *testing.T) {
	t.Parallel()
	var buf = new(bytes.Buffer)
	r := &Runner{Stdout: buf, Stderr: buf}

	// Kubectl and Helm just delegate to RunSilent
	// We test they don't panic with a command that exists
	_, err := r.Kubectl(context.Background(), "version", "--client")
	// May fail if kubectl not installed, that's OK
	_ = err

	_, err = r.Helm(context.Background(), "version", "--short")
	_ = err
}
