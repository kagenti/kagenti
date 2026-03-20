package cli

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cluster"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// DepBuild represents a dependency override: org/repo=ref.
type DepBuild struct {
	Repo string
	Ref  string
}

// ParseDepBuild parses "org/repo=ref" into a DepBuild.
func ParseDepBuild(s string) (DepBuild, error) {
	parts := strings.SplitN(s, "=", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return DepBuild{}, fmt.Errorf("invalid dep build format %q: expected org/repo=ref", s)
	}
	return DepBuild{Repo: parts[0], Ref: parts[1]}, nil
}

// CoreRepos returns the default core dependency repos.
func CoreRepos() []string {
	return []string{
		"kagenti/kagenti-extensions",
		"kagenti/kagenti-operator",
	}
}

// AllRepos returns all buildable dependency repos.
func AllRepos() []string {
	return append(CoreRepos(), "kagenti/agent-examples")
}

func newTestCmd(ctx *AdminContext) *cobra.Command {
	var (
		platform       string
		builds         []string
		buildCore      bool
		buildAll       bool
		buildRef       string
		auto           bool
		skipDestroy    bool
		clusterName    string
	)

	cmd := &cobra.Command{
		Use:   "test",
		Short: "Run full E2E test pipeline with dependency overrides",
		Long: `Run the full Kagenti test pipeline: create cluster, install platform,
build dependencies from source, deploy agents, run E2E tests.

Supports dependency overrides for testing unreleased versions.`,
		Example: `  # Full test on Kind with defaults
  kagenti-admin test --platform kind

  # Test on K3s with core deps from main
  kagenti-admin test --platform k3s --build-core

  # Test with specific dep override
  kagenti-admin test --build kagenti/kagenti-extensions=pr/242

  # CI non-interactive mode
  kagenti-admin test --auto --platform kind --build-core`,
		RunE: func(cmd *cobra.Command, args []string) error {
			start := time.Now()

			// Resolve platform
			p := cluster.Platform(platform)
			if p == "k3s" {
				p = cluster.PlatformRancherDesktop
			}

			// Resolve env from platform
			env := "dev"
			switch p {
			case cluster.PlatformRancherDesktop:
				env = "k3s"
			case cluster.PlatformHyperShift:
				env = "ocp"
			}

			// Parse dep builds
			var depBuilds []DepBuild
			for _, b := range builds {
				db, err := ParseDepBuild(b)
				if err != nil {
					return err
				}
				depBuilds = append(depBuilds, db)
			}

			// Preset expansions
			if buildCore {
				ref := buildRef
				if ref == "" {
					ref = "main"
				}
				for _, repo := range CoreRepos() {
					depBuilds = append(depBuilds, DepBuild{Repo: repo, Ref: ref})
				}
			}
			if buildAll {
				ref := buildRef
				if ref == "" {
					ref = "main"
				}
				for _, repo := range AllRepos() {
					depBuilds = append(depBuilds, DepBuild{Repo: repo, Ref: ref})
				}
			}

			// Print config
			fmt.Fprintf(cmd.OutOrStdout(), "Platform:    %s\n", p)
			fmt.Fprintf(cmd.OutOrStdout(), "Environment: %s\n", env)
			fmt.Fprintf(cmd.OutOrStdout(), "Auto mode:   %v\n", auto)
			if len(depBuilds) > 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "Dep builds:")
				for _, db := range depBuilds {
					fmt.Fprintf(cmd.OutOrStdout(), "  %s = %s\n", db.Repo, db.Ref)
				}
			}
			fmt.Fprintln(cmd.OutOrStdout())

			// Phase 1: Cluster
			if p == cluster.PlatformKind || p == cluster.PlatformRancherDesktop {
				info, err := ctx.ClusterManager.Create(context.Background(), p, clusterName)
				if err != nil {
					return fmt.Errorf("cluster create: %w", err)
				}
				if err := ctx.ClusterManager.Use(context.Background(), info); err != nil {
					return fmt.Errorf("cluster use: %w", err)
				}
			}

			// Phase 2-N: Run pipeline
			repoRoot, err := ctx.getRepoRoot()
			if err != nil {
				return err
			}

			// Set dep build env vars
			if len(depBuilds) > 0 {
				var buildSpecs []string
				for _, db := range depBuilds {
					buildSpecs = append(buildSpecs, db.Repo+"="+db.Ref)
				}
				os.Setenv("KAGENTI_DEP_BUILDS", strings.Join(buildSpecs, ","))
			}

			phases := runner.PlatformPhases(platform)
			envMap := map[string]string{"KAGENTI_ENV": env}
			r := ctx.getRunner()
			results := r.RunPhases(context.Background(), repoRoot, phases, envMap)

			// Summary
			elapsed := time.Since(start)
			passed := 0
			failed := 0
			for _, result := range results {
				if result.Error != nil {
					failed++
				} else {
					passed++
				}
			}

			fmt.Fprintf(cmd.OutOrStdout(), "\n%s Pipeline: %d/%d phases passed (%s)\n",
				map[bool]string{true: "PASSED", false: "FAILED"}[failed == 0],
				passed, passed+failed, elapsed.Round(time.Second))

			// Save test result
			cfg := config.Load()
			cfg.LastTest = &config.TestResult{
				Platform:  string(p),
				Passed:    failed == 0,
				Timestamp: time.Now().UTC().Format(time.RFC3339),
			}
			for _, db := range depBuilds {
				cfg.LastTest.Deps = append(cfg.LastTest.Deps, config.DepBuild{
					Repo: db.Repo,
					Ref:  db.Ref,
				})
			}
			cfg.Save()

			// Destroy cluster if not skipped
			if !skipDestroy && p == cluster.PlatformKind {
				ctx.ClusterManager.Destroy(context.Background(), &cluster.Info{
					Name:     clusterName,
					Platform: p,
				})
			}

			if failed > 0 {
				return fmt.Errorf("%d phase(s) failed", failed)
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&platform, "platform", "kind", "Platform: kind, k3s, hypershift")
	cmd.Flags().StringArrayVar(&builds, "build", nil, "Dependency override: org/repo=ref")
	cmd.Flags().BoolVar(&buildCore, "build-core", false, "Build core deps (extensions + operator)")
	cmd.Flags().BoolVar(&buildAll, "build-all", false, "Build all deps")
	cmd.Flags().StringVar(&buildRef, "ref", "main", "Default ref for --build-core/--build-all")
	cmd.Flags().BoolVar(&auto, "auto", false, "Non-interactive CI mode")
	cmd.Flags().BoolVar(&skipDestroy, "skip-cluster-destroy", false, "Keep cluster after test")
	cmd.Flags().StringVar(&clusterName, "name", "kagenti", "Cluster name (Kind only)")

	// Test type subcommands with --filter
	cmd.AddCommand(
		newTestTypeCmd(ctx, "unit", "Run backend unit tests", "kagenti/backend", "uv run pytest tests/ -v"),
		newTestTypeCmd(ctx, "e2e", "Run backend E2E tests", "kagenti", "uv run pytest tests/e2e/ -v -m 'not observability'"),
		newTestTypeCmd(ctx, "ui", "Run Playwright UI tests", "kagenti/ui-v2", "npx playwright test"),
		newTestTypeCmd(ctx, "agent", "Run agent conversation tests", "kagenti", "uv run pytest tests/e2e/common/test_agent_conversation.py -v"),
		newTestTypeCmd(ctx, "observability", "Run observability tests (Kiali/Phoenix)", "kagenti", "uv run pytest tests/e2e/ -v -m 'observability'"),
		newTestTypeCmd(ctx, "all", "Run all test suites", "kagenti", ""),
	)

	return cmd
}

// newTestTypeCmd creates a subcommand for a specific test type with --filter support.
func newTestTypeCmd(ctx *AdminContext, name, short, workDir, baseCmd string) *cobra.Command {
	var filter string

	cmd := &cobra.Command{
		Use:   name,
		Short: short,
		Example: fmt.Sprintf("  kagenti-admin test %s\n  kagenti-admin test %s --filter \"pattern\"", name, name),
		RunE: func(cmd *cobra.Command, args []string) error {
			repoRoot, err := ctx.getRepoRoot()
			if err != nil {
				return err
			}

			testCmd := baseCmd
			if filter != "" {
				switch name {
				case "ui":
					testCmd = fmt.Sprintf("npx playwright test --grep \"%s\"", filter)
				case "unit", "e2e", "agent", "observability":
					testCmd += fmt.Sprintf(" -k \"%s\"", filter)
				}
			}

			if name == "all" {
				// Run all test suites in sequence
				suites := []struct{ name, dir, cmd string }{
					{"unit", "kagenti/backend", "uv run pytest tests/ -v"},
					{"e2e", "kagenti", "uv run pytest tests/e2e/ -v -m 'not observability'"},
					{"ui", "kagenti/ui-v2", "npx playwright test"},
				}
				for _, s := range suites {
					fmt.Fprintf(cmd.OutOrStdout(), "\n=== %s tests ===\n", s.name)
					r := ctx.getRunner()
					fullCmd := fmt.Sprintf("cd %s/%s && %s", repoRoot, s.dir, s.cmd)
					if _, err := r.Run(context.Background(), "bash", "-c", fullCmd); err != nil {
						fmt.Fprintf(cmd.ErrOrStderr(), "%s tests failed: %v\n", s.name, err)
					}
				}
				return nil
			}

			r := ctx.getRunner()
			fullCmd := fmt.Sprintf("cd %s/%s && %s", repoRoot, workDir, testCmd)
			fmt.Fprintf(cmd.OutOrStdout(), "Running: %s\n\n", testCmd)
			_, err = r.Run(context.Background(), "bash", "-c", fullCmd)
			return err
		},
	}

	cmd.Flags().StringVar(&filter, "filter", "", "Test filter pattern (pytest -k or playwright --grep)")
	return cmd
}
