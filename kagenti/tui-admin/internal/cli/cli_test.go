package cli

import (
	"bytes"
	"testing"

	"github.com/spf13/cobra"
)

func TestNewRootCmd(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()
	if cmd.Use != "kagenti-admin" {
		t.Errorf("expected Use='kagenti-admin', got %q", cmd.Use)
	}

	// Verify subcommands exist
	subs := make(map[string]bool)
	for _, sub := range cmd.Commands() {
		subs[sub.Name()] = true
	}

	expected := []string{"version", "cluster"}
	for _, name := range expected {
		if !subs[name] {
			t.Errorf("missing subcommand: %s", name)
		}
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
		t.Errorf("expected version output to contain 'kagenti-admin', got %q", buf.String())
	}
}

func TestClusterSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	// Find the cluster command
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

	// Verify cluster subcommands
	subs := make(map[string]bool)
	for _, sub := range clusterCmd.Commands() {
		subs[sub.Name()] = true
	}

	expected := []string{"create", "destroy", "list", "use"}
	for _, name := range expected {
		if !subs[name] {
			t.Errorf("missing cluster subcommand: %s", name)
		}
	}
}

func TestAllRootSubcommands(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	subs := make(map[string]bool)
	for _, sub := range cmd.Commands() {
		subs[sub.Name()] = true
	}

	expected := []string{"version", "cluster", "run", "test"}
	for _, name := range expected {
		if !subs[name] {
			t.Errorf("missing root subcommand: %s", name)
		}
	}
}

func TestClusterCreateFlags(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var createCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "cluster" {
			for _, csub := range sub.Commands() {
				if csub.Name() == "create" {
					createCmd = csub
					break
				}
			}
		}
	}
	if createCmd == nil {
		t.Fatal("cluster create command not found")
	}

	flags := []string{"platform", "name"}
	for _, name := range flags {
		if createCmd.Flags().Lookup(name) == nil {
			t.Errorf("missing flag: --%s", name)
		}
	}
}

func TestRunInstallFlags(t *testing.T) {
	t.Parallel()
	cmd := NewRootCmd()

	var installCmd *cobra.Command
	for _, sub := range cmd.Commands() {
		if sub.Name() == "run" {
			for _, rsub := range sub.Commands() {
				if rsub.Name() == "install" {
					installCmd = rsub
					break
				}
			}
		}
	}
	if installCmd == nil {
		t.Fatal("run install command not found")
	}

	if installCmd.Flags().Lookup("env") == nil {
		t.Error("missing --env flag on run install")
	}
}
