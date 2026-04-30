package cli

import (
	"bytes"
	"testing"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

func TestKnownComponents(t *testing.T) {
	t.Parallel()
	comps := KnownComponents()
	if len(comps) < 5 {
		t.Errorf("expected at least 5 known components, got %d", len(comps))
	}
	names := make(map[string]bool)
	for _, c := range comps {
		names[c.Name] = true
		if c.Namespace == "" {
			t.Errorf("component %s has empty namespace", c.Name)
		}
		if c.Label == "" {
			t.Errorf("component %s has empty label", c.Name)
		}
	}
	for _, expected := range []string{"ui", "backend", "operator", "keycloak", "weather-tool"} {
		if !names[expected] {
			t.Errorf("missing component: %s", expected)
		}
	}
}

func TestFindComponent(t *testing.T) {
	t.Parallel()
	comp, err := FindComponent("ui")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if comp.Namespace != "kagenti-system" {
		t.Errorf("ui namespace: got %q, want kagenti-system", comp.Namespace)
	}
}

func TestFindComponentNotFound(t *testing.T) {
	t.Parallel()
	_, err := FindComponent("nonexistent")
	if err == nil {
		t.Error("expected error for unknown component")
	}
}

func TestStatusDashboard(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("COMPONENT")) {
		t.Error("dashboard should show COMPONENT header")
	}
}

func TestStatusComponent(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status", "ui"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("Component: ui")) {
		t.Error("should show component name")
	}
}

func TestStatusLastTestNoResults(t *testing.T) {
	// Cannot use t.Parallel with t.Setenv
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"status", "last-test"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("No test results")) {
		t.Errorf("should say no test results, got: %s", buf.String())
	}
}

func TestStatusLastTestWithResults(t *testing.T) {
	// Cannot use t.Parallel with t.Setenv
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	cfg := &config.Config{
		LastTest: &config.TestResult{
			Platform:  "kind",
			Passed:    true,
			Timestamp: "2026-03-20T10:00:00Z",
			Deps:      []config.DepBuild{{Repo: "kagenti/ext", Ref: "main", Commit: "abc123"}},
		},
	}
	cfg.Save()

	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"status", "last-test"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("PASSED")) {
		t.Error("should show PASSED")
	}
	if !bytes.Contains(buf.Bytes(), []byte("kagenti/ext")) {
		t.Error("should show dep repo")
	}
}

func TestStatusDeps(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status", "deps"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("COMPONENT")) {
		t.Error("should show COMPONENT header")
	}
}

func TestStatusImages(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status", "images"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("Running Images")) {
		t.Error("should show Running Images header")
	}
}

func TestContains(t *testing.T) {
	t.Parallel()
	if !contains("hello world", "world") {
		t.Error("should contain 'world'")
	}
	if contains("hello", "world") {
		t.Error("should not contain 'world'")
	}
	if !contains("test", "") {
		t.Error("empty substr should match")
	}
}

func TestSplitLines(t *testing.T) {
	t.Parallel()
	lines := splitLines("a\nb\nc")
	if len(lines) != 3 {
		t.Errorf("expected 3 lines, got %d", len(lines))
	}
}

func TestSplitFields(t *testing.T) {
	t.Parallel()
	fields := splitFields("  Running   true  ")
	if len(fields) != 2 {
		t.Errorf("expected 2 fields, got %d: %v", len(fields), fields)
	}
	if fields[0] != "Running" || fields[1] != "true" {
		t.Errorf("got %v", fields)
	}
}

// Integration scenario: full status flow
func TestStatusFullScenario(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		if len(args) > 2 && args[1] == "current-context" {
			return &runner.Result{Stdout: "kind-kagenti"}, nil
		}
		if len(args) > 2 && args[0] == "get" && args[1] == "pods" {
			return &runner.Result{Stdout: "Running true"}, nil
		}
		if len(args) > 2 && args[0] == "get" && args[1] == "deployment" {
			return &runner.Result{Stdout: "ghcr.io/kagenti/kagenti/ui-v2:0.3.0"}, nil
		}
		return &runner.Result{Stdout: ""}, nil
	})

	ctx, _ := newTestContext(t)
	ctx.ClusterManager.Runner = mock
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)

	// Run status dashboard
	cmd.SetArgs([]string{"status"})
	cmd.Execute()
	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("Platform:")) {
		t.Error("should show platform")
	}
}
