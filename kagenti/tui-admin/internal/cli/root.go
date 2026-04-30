// Package cli implements the kagenti-admin CLI commands.
package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cluster"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/version"
)

// AdminContext holds shared state for all admin CLI subcommands.
// Fields can be overridden for testing.
type AdminContext struct {
	ClusterManager *cluster.Manager
	PhaseRunner    *runner.Runner // Runner for phase execution (nil = create new)
	RepoRoot       string        // Override for FindRepoRoot (empty = auto-detect)
}

// getRepoRoot returns the repo root, using the override if set.
func (c *AdminContext) getRepoRoot() (string, error) {
	if c.RepoRoot != "" {
		return c.RepoRoot, nil
	}
	return runner.FindRepoRoot()
}

// getRunner returns the phase runner, creating one if not injected.
func (c *AdminContext) getRunner() *runner.Runner {
	if c.PhaseRunner != nil {
		return c.PhaseRunner
	}
	return runner.New()
}

// NewRootCmd creates the root cobra command with all subcommands.
func NewRootCmd() *cobra.Command {
	return NewRootCmdWithContext(&AdminContext{
		ClusterManager: cluster.NewManager(),
	})
}

// NewRootCmdWithContext creates the root command with an injected context (for testing).
func NewRootCmdWithContext(ctx *AdminContext) *cobra.Command {

	root := &cobra.Command{
		Use:          "kagenti-admin",
		Short:        "Kagenti Admin CLI — cluster lifecycle, testing, and release coordination",
		Long:         "kagenti-admin manages Kubernetes clusters, deploys Kagenti platform, runs E2E tests, and coordinates multi-repo releases.",
		SilenceUsage: true,
	}

	root.AddCommand(
		newVersionCmd(),
		newPreflightCmd(ctx),
		newClusterCmd(ctx),
		newStatusCmd(ctx),
		newRunCmd(ctx),
		newTestCmd(ctx),
		newLogsCmd(ctx),
		newRolloutCmd(ctx),
		newWorkspaceCmd(ctx),
	)

	return root
}

func newVersionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print the version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), "kagenti-admin", version.Version)
			return nil
		},
	}
}
