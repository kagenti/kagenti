package cli

import (
	"testing"

	"github.com/spf13/cobra"
)

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
				t.Errorf("unexpected error for %q: %v", tt.input, err)
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
	all := AllRepos()
	core := CoreRepos()
	if len(all) <= len(core) {
		t.Errorf("AllRepos should have more repos than CoreRepos")
	}
}

func TestTestCmdExists(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var testCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "test" {
			testCmd = sub
			break
		}
	}
	if testCmd == nil {
		t.Fatal("test subcommand not found")
	}

	// Verify flags exist
	flags := []string{"platform", "build", "build-core", "build-all", "auto", "skip-cluster-destroy"}
	for _, name := range flags {
		if testCmd.Flags().Lookup(name) == nil {
			t.Errorf("missing flag: --%s", name)
		}
	}
}

func TestRunCmdSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var runCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			runCmd = sub
			break
		}
	}
	if runCmd == nil {
		t.Fatal("run subcommand not found")
	}

	subs := make(map[string]bool)
	for _, sub := range runCmd.Commands() {
		subs[sub.Name()] = true
	}

	expected := []string{"install", "deploy-agents", "e2e", "all"}
	for _, name := range expected {
		if !subs[name] {
			t.Errorf("missing run subcommand: %s", name)
		}
	}
}
