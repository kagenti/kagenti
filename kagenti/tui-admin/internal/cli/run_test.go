package cli

import (
	"bytes"
	"testing"

	"github.com/spf13/cobra"
)

func TestRunCmdStructure(t *testing.T) {
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

	if runCmd.Short == "" {
		t.Error("run command should have short description")
	}

	// Verify all subcommands have short descriptions
	for _, sub := range runCmd.Commands() {
		if sub.Short == "" {
			t.Errorf("run %s should have short description", sub.Name())
		}
	}
}

func TestRunAllFlags(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var allCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			for _, rsub := range sub.Commands() {
				if rsub.Name() == "all" {
					allCmd = rsub
					break
				}
			}
		}
	}
	if allCmd == nil {
		t.Fatal("run all command not found")
	}

	if allCmd.Flags().Lookup("env") == nil {
		t.Error("run all should have --env flag")
	}
}

func TestRunE2EAlias(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var e2eCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			for _, rsub := range sub.Commands() {
				if rsub.Name() == "e2e" {
					e2eCmd = rsub
					break
				}
			}
		}
	}
	if e2eCmd == nil {
		t.Fatal("run e2e command not found")
	}

	// e2e should have "test" as an alias
	found := false
	for _, alias := range e2eCmd.Aliases {
		if alias == "test" {
			found = true
			break
		}
	}
	if !found {
		t.Error("run e2e should have 'test' alias")
	}
}

func TestRunCmdHelp(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	var buf bytes.Buffer
	cmd.SetOut(&buf)
	cmd.SetArgs([]string{"run", "--help"})

	err := cmd.Execute()
	if err != nil {
		t.Fatalf("run --help failed: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("install")) {
		t.Error("run --help should mention install")
	}
}
