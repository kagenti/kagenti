package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// runPhasesByName looks up phases by name and executes them.
func runPhasesByName(ctx *AdminContext, names []string, env map[string]string) error {
	repoRoot, err := ctx.getRepoRoot()
	if err != nil {
		return err
	}

	allPhases := runner.PlatformPhases("")
	phaseMap := make(map[string]runner.Phase, len(allPhases))
	for _, p := range allPhases {
		phaseMap[p.Name] = p
	}

	var selected []runner.Phase
	for _, name := range names {
		p, ok := phaseMap[name]
		if !ok {
			return fmt.Errorf("unknown phase: %s", name)
		}
		selected = append(selected, p)
	}

	r := ctx.getRunner()
	results := r.RunPhases(context.Background(), repoRoot, selected, env)

	for _, result := range results {
		if result.Error != nil {
			return fmt.Errorf("phase %s failed: %w", result.Phase.Name, result.Error)
		}
	}
	return nil
}

func newRunCmd(ctx *AdminContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "run <phase>",
		Short: "Re-run individual deployment phases",
		Long:  "Run specific phases of the Kagenti deployment pipeline. Use 'run all' for the full pipeline.",
	}

	cmd.AddCommand(
		newRunInstallCmd(ctx),
		newRunDeployAgentsCmd(ctx),
		newRunE2ECmd(ctx),
		newRunAllCmd(ctx),
	)

	return cmd
}

func newRunInstallCmd(ctx *AdminContext) *cobra.Command {
	var env string

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install Kagenti platform (Helm + Ansible)",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runPhasesByName(ctx,
				[]string{"secrets", "install", "wait-platform", "dockerhost", "crds"},
				map[string]string{"KAGENTI_ENV": env},
			)
		},
	}

	cmd.Flags().StringVar(&env, "env", "dev", "Environment: dev, k3s, ocp")
	return cmd
}

func newRunDeployAgentsCmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:   "deploy-agents",
		Short: "Build and deploy test agents (weather-tool + weather-service)",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runPhasesByName(ctx, []string{"deploy-agents"}, nil)
		},
	}
}

func newRunE2ECmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:     "e2e",
		Short:   "Run E2E tests only",
		Aliases: []string{"test"},
		RunE: func(cmd *cobra.Command, args []string) error {
			return runPhasesByName(ctx, []string{"e2e"}, nil)
		},
	}
}

func newRunAllCmd(ctx *AdminContext) *cobra.Command {
	var env string

	cmd := &cobra.Command{
		Use:   "all",
		Short: "Run the full deployment pipeline (install + agents + test)",
		RunE: func(cmd *cobra.Command, args []string) error {
			repoRoot, err := ctx.getRepoRoot()
			if err != nil {
				return err
			}

			phases := runner.PlatformPhases("")
			envMap := map[string]string{"KAGENTI_ENV": env}
			r := ctx.getRunner()
			results := r.RunPhases(context.Background(), repoRoot, phases, envMap)

			passed := 0
			failed := 0
			for _, result := range results {
				if result.Error != nil {
					failed++
				} else {
					passed++
				}
			}

			fmt.Fprintf(cmd.OutOrStdout(), "\nPipeline: %d/%d phases passed\n", passed, passed+failed)
			if failed > 0 {
				return fmt.Errorf("%d phase(s) failed", failed)
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&env, "env", "dev", "Environment: dev, k3s, ocp")
	return cmd
}
