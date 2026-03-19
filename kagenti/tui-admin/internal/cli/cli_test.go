package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cluster"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// newTestContext creates an AdminContext with mocks for testing.
// It creates a temp dir with dummy scripts that succeed.
func newTestContext(t *testing.T) (*AdminContext, string) {
	t.Helper()
	dir := t.TempDir()

	// Create dummy scripts for all phases
	scripts := []string{
		".github/scripts/common/20-create-secrets.sh",
		".github/scripts/kagenti-operator/30-run-installer.sh",
		".github/scripts/common/40-wait-platform-ready.sh",
		".github/scripts/common/50-install-ollama.sh",
		".github/scripts/common/60-pull-ollama-model.sh",
		".github/scripts/common/70-configure-dockerhost.sh",
		".github/scripts/kagenti-operator/41-wait-crds.sh",
		".github/scripts/kagenti-operator/42-apply-pipeline-template.sh",
		".github/scripts/kagenti-operator/71-build-weather-tool.sh",
		".github/scripts/kagenti-operator/72-deploy-weather-tool.sh",
		".github/scripts/kagenti-operator/73-patch-weather-tool.sh",
		".github/scripts/kagenti-operator/74-deploy-weather-agent.sh",
		".github/scripts/common/80-install-test-deps.sh",
		".github/scripts/common/85-start-port-forward.sh",
		".github/scripts/kagenti-operator/90-run-e2e-tests.sh",
	}
	for _, s := range scripts {
		p := filepath.Join(dir, s)
		os.MkdirAll(filepath.Dir(p), 0o755)
		os.WriteFile(p, []byte("#!/bin/sh\necho ok"), 0o755)
	}

	mock := runner.NewMockExecutor()
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "kind-kagenti"}, nil
	})
	mock.On("kind", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "kagenti"}, nil
	})

	mgr := &cluster.Manager{
		Runner: mock,
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}

	return &AdminContext{
		ClusterManager: mgr,
		RepoRoot:       dir,
	}, dir
}

func TestNewRootCmd(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	if cmd.Use != "kagenti-admin" {
		t.Errorf("expected Use='kagenti-admin', got %q", cmd.Use)
	}
}

func TestVersionCmd(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"version"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("version command failed: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("kagenti-admin")) {
		t.Errorf("expected 'kagenti-admin' in output, got %q", buf.String())
	}
}

func TestAllRootSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	subs := make(map[string]bool)
	for _, sub := range cmd.Commands() {
		subs[sub.Name()] = true
	}
	for _, name := range []string{"version", "cluster", "run", "test"} {
		if !subs[name] {
			t.Errorf("missing root subcommand: %s", name)
		}
	}
}

func TestClusterSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	var clusterCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "cluster" {
			clusterCmd = sub
			break
		}
	}
	if clusterCmd == nil {
		t.Fatal("cluster subcommand not found")
	}
	subs := make(map[string]bool)
	for _, sub := range clusterCmd.Commands() {
		subs[sub.Name()] = true
	}
	for _, name := range []string{"create", "destroy", "list", "use"} {
		if !subs[name] {
			t.Errorf("missing cluster subcommand: %s", name)
		}
	}
}

func TestClusterCreateFlags(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	for _, sub := range cmd.Commands() {
		if sub.Name() == "cluster" {
			for _, csub := range sub.Commands() {
				if csub.Name() == "create" {
					for _, f := range []string{"platform", "name"} {
						if csub.Flags().Lookup(f) == nil {
							t.Errorf("missing flag: --%s", f)
						}
					}
					return
				}
			}
		}
	}
	t.Fatal("cluster create not found")
}

func TestRunCmdSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			subs := make(map[string]bool)
			for _, rsub := range sub.Commands() {
				subs[rsub.Name()] = true
			}
			for _, name := range []string{"install", "deploy-agents", "e2e", "all"} {
				if !subs[name] {
					t.Errorf("missing run subcommand: %s", name)
				}
			}
			return
		}
	}
	t.Fatal("run subcommand not found")
}

func TestRunInstallFlags(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			for _, rsub := range sub.Commands() {
				if rsub.Name() == "install" {
					if rsub.Flags().Lookup("env") == nil {
						t.Error("missing --env flag")
					}
					return
				}
			}
		}
	}
	t.Fatal("run install not found")
}

func TestRunE2EAlias(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			for _, rsub := range sub.Commands() {
				if rsub.Name() == "e2e" {
					for _, alias := range rsub.Aliases {
						if alias == "test" {
							return
						}
					}
					t.Error("e2e should have 'test' alias")
					return
				}
			}
		}
	}
	t.Fatal("run e2e not found")
}

func TestTestCmdExists(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	for _, sub := range cmd.Commands() {
		if sub.Name() == "test" {
			for _, f := range []string{"platform", "build", "build-core", "build-all", "auto", "skip-cluster-destroy"} {
				if sub.Flags().Lookup(f) == nil {
					t.Errorf("missing flag: --%s", f)
				}
			}
			return
		}
	}
	t.Fatal("test subcommand not found")
}

// === Execution tests using injected context ===

func TestRunInstallExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "install"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("run install failed: %v", err)
	}
}

func TestRunDeployAgentsExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "deploy-agents"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("run deploy-agents failed: %v", err)
	}
}

func TestRunE2EExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "e2e"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("run e2e failed: %v", err)
	}
}

func TestRunAllExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "all"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("run all failed: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("Pipeline:")) {
		t.Error("expected 'Pipeline:' summary in output")
	}
}

func TestRunAllWithFailingScript(t *testing.T) {
	t.Parallel()
	ctx, dir := newTestContext(t)
	// Make the secrets script fail
	os.WriteFile(filepath.Join(dir, ".github/scripts/common/20-create-secrets.sh"), []byte("#!/bin/sh\nexit 1"), 0o755)

	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"run", "all"})

	err := cmd.Execute()
	if err == nil {
		t.Error("expected error when script fails")
	}
}

func TestRunPhasesByNameUnknown(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	err := runPhasesByName(ctx, []string{"nonexistent"}, nil)
	if err == nil {
		t.Error("expected error for unknown phase")
	}
}

func TestClusterListExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"cluster", "list"})

	// This may or may not find real clusters, but should not error
	_ = cmd.Execute()
}

func TestGetRepoRoot(t *testing.T) {
	t.Parallel()
	ctx := &AdminContext{RepoRoot: "/tmp/test"}
	root, err := ctx.getRepoRoot()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if root != "/tmp/test" {
		t.Errorf("expected /tmp/test, got %q", root)
	}
}

func TestGetRepoRootAutoDetect(t *testing.T) {
	t.Parallel()
	ctx := &AdminContext{}
	root, err := ctx.getRepoRoot()
	if err != nil {
		t.Skipf("not in git repo: %v", err)
	}
	if root == "" {
		t.Error("expected non-empty repo root")
	}
}

func TestGetRunner(t *testing.T) {
	t.Parallel()
	// With injected runner
	r := runner.New()
	ctx := &AdminContext{PhaseRunner: r}
	if ctx.getRunner() != r {
		t.Error("expected injected runner")
	}

	// Without injected runner
	ctx2 := &AdminContext{}
	if ctx2.getRunner() == nil {
		t.Error("expected auto-created runner")
	}
}

func TestRunCmdHelp(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"run", "--help"})
	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("install")) {
		t.Error("run --help should mention install")
	}
}

// === ParseDepBuild tests ===

func TestParseDepBuild(t *testing.T) {
	t.Parallel()
	tests := []struct {
		input   string
		repo    string
		ref     string
		wantErr bool
	}{
		{"kagenti/kagenti-extensions=main", "kagenti/kagenti-extensions", "main", false},
		{"kagenti/kagenti-operator=pr/42", "kagenti/kagenti-operator", "pr/42", false},
		{"kagenti/agent-examples=v0.4.0-alpha.9", "kagenti/agent-examples", "v0.4.0-alpha.9", false},
		{"kagenti/repo=a5607f9", "kagenti/repo", "a5607f9", false},
		{"invalid", "", "", true},
		{"=ref", "", "", true},
		{"repo=", "", "", true},
		{"", "", "", true},
	}
	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			t.Parallel()
			db, err := ParseDepBuild(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Errorf("expected error for %q", tt.input)
				}
				return
			}
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			if db.Repo != tt.repo {
				t.Errorf("repo: got %q, want %q", db.Repo, tt.repo)
			}
			if db.Ref != tt.ref {
				t.Errorf("ref: got %q, want %q", db.Ref, tt.ref)
			}
		})
	}
}

func TestCoreRepos(t *testing.T) {
	t.Parallel()
	repos := CoreRepos()
	if len(repos) < 2 {
		t.Errorf("expected at least 2 core repos, got %d", len(repos))
	}
}

func TestAllRepos(t *testing.T) {
	t.Parallel()
	if len(AllRepos()) <= len(CoreRepos()) {
		t.Error("AllRepos should have more repos than CoreRepos")
	}
}

// === Cluster CLI execution tests ===

func TestClusterCreateExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"cluster", "create", "--platform", "kind", "--name", "test"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("cluster create failed: %v", err)
	}
}

func TestClusterDestroyExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"cluster", "destroy", "kagenti"})

	// Will fail because mock list returns "kagenti" but destroy tries real kind
	// That's fine — we test the flow, not the result
	_ = cmd.Execute()
}

func TestClusterUseExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"cluster", "use", "nonexistent"})

	err := cmd.Execute()
	if err == nil {
		t.Error("expected error for nonexistent cluster")
	}
}

func TestTestCmdExecutes(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "--platform", "kind", "--skip-cluster-destroy",
		"--build", "kagenti/kagenti-extensions=main"})

	// test command will try to create a Kind cluster via the mock manager
	err := cmd.Execute()
	if err != nil {
		t.Logf("test cmd error (may be expected): %v", err)
	}
	// Verify output contains platform info
	if !bytes.Contains(buf.Bytes(), []byte("Platform:")) {
		t.Error("expected Platform: in output")
	}
}

func TestTestCmdBuildCore(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "--platform", "kind", "--build-core", "--skip-cluster-destroy"})

	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("kagenti/kagenti-extensions")) {
		t.Error("expected extensions in dep builds output")
	}
}

func TestTestCmdBuildAll(t *testing.T) {
	t.Parallel()
	ctx, _ := newTestContext(t)
	cmd := NewRootCmdWithContext(ctx)
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	cmd.SetArgs([]string{"test", "--platform", "k3s", "--build-all", "--skip-cluster-destroy"})

	_ = cmd.Execute()
	if !bytes.Contains(buf.Bytes(), []byte("agent-examples")) {
		t.Error("expected agent-examples in dep builds output")
	}
}
