package cli

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

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
			repoRoot, err := runner.FindRepoRoot()
			if err != nil {
				return err
			}

			phases := []runner.Phase{
				runner.PlatformPhases("")[0], // secrets
				runner.PlatformPhases("")[1], // install
				runner.PlatformPhases("")[2], // wait-platform
				runner.PlatformPhases("")[4], // dockerhost
				runner.PlatformPhases("")[5], // crds
			}

			envMap := map[string]string{"KAGENTI_ENV": env}
			r := runner.New()
			results := r.RunPhases(context.Background(), repoRoot, phases, envMap)

			for _, result := range results {
				if result.Error != nil {
					return fmt.Errorf("install failed at phase %s: %w", result.Phase.Name, result.Error)
				}
			}
			return nil
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
			repoRoot, err := runner.FindRepoRoot()
			if err != nil {
				return err
			}

			phases := []runner.Phase{runner.PlatformPhases("")[6]} // deploy-agents
			r := runner.New()
			results := r.RunPhases(context.Background(), repoRoot, phases, nil)

			for _, result := range results {
				if result.Error != nil {
					return fmt.Errorf("deploy-agents failed: %w", result.Error)
				}
			}
			return nil
		},
	}
}

func newRunE2ECmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:     "e2e",
		Short:   "Run E2E tests only",
		Aliases: []string{"test"},
		RunE: func(cmd *cobra.Command, args []string) error {
			repoRoot, err := runner.FindRepoRoot()
			if err != nil {
				return err
			}

			phases := []runner.Phase{runner.PlatformPhases("")[7]} // e2e
			r := runner.New()
			results := r.RunPhases(context.Background(), repoRoot, phases, nil)

			for _, result := range results {
				if result.Error != nil {
					return fmt.Errorf("e2e tests failed: %w", result.Error)
				}
			}
			return nil
		},
	}
}

func newRunAllCmd(ctx *AdminContext) *cobra.Command {
	var env string

	cmd := &cobra.Command{
		Use:   "all",
		Short: "Run the full deployment pipeline (install + agents + test)",
		RunE: func(cmd *cobra.Command, args []string) error {
			repoRoot, err := runner.FindRepoRoot()
			if err != nil {
				return err
			}

			phases := runner.PlatformPhases("")
			envMap := map[string]string{"KAGENTI_ENV": env}
			r := runner.New()
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
