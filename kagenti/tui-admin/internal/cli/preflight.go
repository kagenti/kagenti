package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

func newPreflightCmd(ctx *AdminContext) *cobra.Command {
	var platform string

	cmd := &cobra.Command{
		Use:   "preflight",
		Short: "Check local dependencies for a platform",
		Example: `  kagenti-admin preflight --platform kind
  kagenti-admin preflight --platform k3s
  kagenti-admin preflight --platform hypershift`,
		RunE: func(cmd *cobra.Command, args []string) error {
			passed, _ := runner.RunPreflightChecks(cmd.OutOrStdout(), platform)
			if !passed {
				fmt.Fprintln(cmd.ErrOrStderr(), "Preflight checks failed.")
				os.Exit(1)
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&platform, "platform", "kind", "Platform: kind, k3s, hypershift")
	return cmd
}
