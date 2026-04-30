package cli

import (
	"bytes"
	"testing"
)

// Integration scenarios: test full CLI flows with mock scripts.
// Each scenario simulates a real user workflow end-to-end.

// Scenario 1: Developer deploys to Kind, runs E2E, checks status
func TestScenario_KindDevFlow(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	// Step 1: preflight
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"preflight", "--platform", "kind"})
	if err := cmd.Execute(); err != nil {
		t.Logf("preflight: %v (expected if deps missing)", err)
	}

	// Step 2: run install
	buf.Reset()
	cmd = NewRootCmdWithContext(ctx)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "install"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("run install failed: %v", err)
	}

	// Step 3: run deploy-agents
	buf.Reset()
	cmd = NewRootCmdWithContext(ctx)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "deploy-agents"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("run deploy-agents failed: %v", err)
	}

	// Step 4: run e2e
	buf.Reset()
	cmd = NewRootCmdWithContext(ctx)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "e2e"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("run e2e failed: %v", err)
	}

	// Step 5: status
	buf.Reset()
	cmd = NewRootCmdWithContext(ctx)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status"})
	cmd.Execute()
}

// Scenario 2: Test with dep overrides and filter
func TestScenario_TestWithOverrides(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test",
		"--platform", "kind",
		"--build", "kagenti/kagenti-extensions=pr/242",
		"--build-core",
		"--skip-cluster-destroy",
	})
	_ = cmd.Execute()

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("kagenti/kagenti-extensions")) {
		t.Error("should show dep override in output")
	}
	if !bytes.Contains([]byte(output), []byte("build-core")) || !bytes.Contains([]byte(output), []byte("extensions")) {
		// At minimum should show the platform
		if !bytes.Contains([]byte(output), []byte("Platform:")) {
			t.Error("should show platform info")
		}
	}
}

// Scenario 3: Logs command
func TestScenario_Logs(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"logs", "ui", "--tail", "10"})
	// Will fail (no real cluster) but should not panic
	_ = cmd.Execute()
}

// Scenario 4: Logs with agent subcommand
func TestScenario_LogsAgent(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"logs", "agent", "weather-service"})
	_ = cmd.Execute()
}

// Scenario 5: Rollout
func TestScenario_Rollout(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"rollout", "ui"})
	_ = cmd.Execute()
}

// Scenario 6: Rollout all
func TestScenario_RolloutAll(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"rollout", "all"})
	_ = cmd.Execute()
}

// Scenario 7: Test type subcommands
func TestScenario_TestUnit(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "unit", "--filter", "test_auth"})
	_ = cmd.Execute()
}

func TestScenario_TestE2E(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "e2e", "--filter", "keycloak"})
	_ = cmd.Execute()
}

func TestScenario_TestUI(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "ui", "--filter", "agent-chat"})
	_ = cmd.Execute()
}

func TestScenario_TestAll(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "all"})
	_ = cmd.Execute()
}

// Scenario 8: Workspace commands
func TestScenario_WorkspaceList(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"workspace", "list", "sandbox-legion"})
	_ = cmd.Execute()
}

func TestScenario_WorkspaceDownload(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"workspace", "download", "sandbox-legion", "--config-ref", "my-test"})
	_ = cmd.Execute()
}

// Scenario 9: Unknown component
func TestScenario_StatusUnknownComponent(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"status", "nonexistent"})
	err := cmd.Execute()
	if err == nil {
		t.Error("expected error for unknown component")
	}
}

// Scenario 10: Rollout unknown component
func TestScenario_RolloutUnknown(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"rollout", "nonexistent"})
	err := cmd.Execute()
	if err == nil {
		t.Error("expected error for unknown component")
	}
}
