// Package cli implements the kagenti-admin CLI commands.
package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cluster"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/version"
)

// AdminContext holds shared state for all admin CLI subcommands.
type AdminContext struct {
	ClusterManager *cluster.Manager
}

// NewRootCmd creates the root cobra command with all subcommands.
func NewRootCmd() *cobra.Command {
	ctx := &AdminContext{
		ClusterManager: cluster.NewManager(),
	}

	root := &cobra.Command{
		Use:          "kagenti-admin",
		Short:        "Kagenti Admin CLI — cluster lifecycle, testing, and release coordination",
		Long:         "kagenti-admin manages Kubernetes clusters, deploys Kagenti platform, runs E2E tests, and coordinates multi-repo releases.",
		SilenceUsage: true,
	}

	root.AddCommand(
		newVersionCmd(),
		newClusterCmd(ctx),
		newRunCmd(ctx),
		newTestCmd(ctx),
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
