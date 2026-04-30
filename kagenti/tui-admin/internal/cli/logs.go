package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"
)

func newLogsCmd(ctx *AdminContext) *cobra.Command {
	var follow bool
	var tail int

	cmd := &cobra.Command{
		Use:   "logs <component>",
		Short: "Stream pod logs for a component",
		Example: `  kagenti-admin logs ui
  kagenti-admin logs backend -f
  kagenti-admin logs agent weather-service --tail 100`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]

			// Handle "agent <name>" as two args
			if name == "agent" && len(args) > 1 {
				name = args[1]
			}

			comp, err := FindComponent(name)
			if err != nil {
				return err
			}

			kubectlArgs := []string{"logs", "-n", comp.Namespace, "-l", comp.Label, "--all-containers=true"}
			if follow {
				kubectlArgs = append(kubectlArgs, "-f")
			}
			if tail > 0 {
				kubectlArgs = append(kubectlArgs, fmt.Sprintf("--tail=%d", tail))
			}

			r := ctx.getRunner()
			_, err = r.Run(context.Background(), "kubectl", kubectlArgs...)
			return err
		},
	}

	cmd.Flags().BoolVarP(&follow, "follow", "f", false, "Follow log output")
	cmd.Flags().IntVar(&tail, "tail", 50, "Number of lines to show from end")

	return cmd
}
