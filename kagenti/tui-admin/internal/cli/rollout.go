package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"
)

func newRolloutCmd(ctx *AdminContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "rollout <component>",
		Short: "Restart a component (kubectl rollout restart)",
		Example: `  kagenti-admin rollout ui
  kagenti-admin rollout backend
  kagenti-admin rollout agent weather-service
  kagenti-admin rollout all`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]

			if name == "all" {
				return rolloutAll(ctx, cmd)
			}

			// Handle "agent <name>"
			if name == "agent" && len(args) > 1 {
				name = args[1]
			}

			comp, err := FindComponent(name)
			if err != nil {
				return err
			}

			deploy := comp.Deployment
			if deploy == "" {
				deploy = comp.Name
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Restarting %s in %s...\n", deploy, comp.Namespace)
			r := ctx.getRunner()
			_, err = r.RunSilent(context.Background(), "kubectl", "rollout", "restart",
				"deployment/"+deploy, "-n", comp.Namespace)
			if err != nil {
				return fmt.Errorf("rollout restart %s: %w", name, err)
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Rollout restart initiated for %s\n", name)
			return nil
		},
	}

	return cmd
}

func rolloutAll(ctx *AdminContext, cmd *cobra.Command) error {
	r := ctx.getRunner()
	fmt.Fprintln(cmd.OutOrStdout(), "Restarting all kagenti-system deployments...")
	_, err := r.RunSilent(context.Background(), "kubectl", "rollout", "restart",
		"deployment", "-n", "kagenti-system")
	if err != nil {
		return fmt.Errorf("rollout restart all: %w", err)
	}
	fmt.Fprintln(cmd.OutOrStdout(), "All kagenti-system deployments restarting")
	return nil
}
