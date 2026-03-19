package runner

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// Phase represents a deployment pipeline phase.
type Phase struct {
	Name        string
	Description string
	Scripts     []string // Scripts to run relative to repo root
}

// PlatformPhases returns the deployment phases for a given platform.
func PlatformPhases(platform string) []Phase {
	common := []Phase{
		{
			Name:        "secrets",
			Description: "Create secret values",
			Scripts:     []string{".github/scripts/common/20-create-secrets.sh"},
		},
		{
			Name:        "install",
			Description: "Install Kagenti platform (Ansible + Helm)",
			Scripts:     []string{".github/scripts/kagenti-operator/30-run-installer.sh"},
		},
		{
			Name:        "wait-platform",
			Description: "Wait for platform pods to be ready",
			Scripts:     []string{".github/scripts/common/40-wait-platform-ready.sh"},
		},
		{
			Name:        "ollama",
			Description: "Install and configure Ollama",
			Scripts: []string{
				".github/scripts/common/50-install-ollama.sh",
				".github/scripts/common/60-pull-ollama-model.sh",
			},
		},
		{
			Name:        "dockerhost",
			Description: "Configure dockerhost for host Ollama access",
			Scripts:     []string{".github/scripts/common/70-configure-dockerhost.sh"},
		},
		{
			Name:        "crds",
			Description: "Wait for CRDs and apply pipeline template",
			Scripts: []string{
				".github/scripts/kagenti-operator/41-wait-crds.sh",
				".github/scripts/kagenti-operator/42-apply-pipeline-template.sh",
			},
		},
		{
			Name:        "deploy-agents",
			Description: "Build and deploy test agents",
			Scripts: []string{
				".github/scripts/kagenti-operator/71-build-weather-tool.sh",
				".github/scripts/kagenti-operator/72-deploy-weather-tool.sh",
				".github/scripts/kagenti-operator/73-patch-weather-tool.sh",
				".github/scripts/kagenti-operator/74-deploy-weather-agent.sh",
			},
		},
		{
			Name:        "e2e",
			Description: "Run E2E tests",
			Scripts: []string{
				".github/scripts/common/80-install-test-deps.sh",
				".github/scripts/common/85-start-port-forward.sh",
				".github/scripts/kagenti-operator/90-run-e2e-tests.sh",
			},
		},
	}

	return common
}

// PhaseResult holds the outcome of running a phase.
type PhaseResult struct {
	Phase    Phase
	Duration time.Duration
	Error    error
}

// RunPhase executes a single deployment phase.
func (r *Runner) RunPhase(ctx context.Context, repoRoot string, phase Phase, env map[string]string) *PhaseResult {
	start := time.Now()
	result := &PhaseResult{Phase: phase}

	for _, script := range phase.Scripts {
		scriptPath := filepath.Join(repoRoot, script)
		if _, err := os.Stat(scriptPath); os.IsNotExist(err) {
			result.Error = fmt.Errorf("script not found: %s", scriptPath)
			result.Duration = time.Since(start)
			return result
		}

		cmd := []string{scriptPath}

		// Add env-specific args
		if phase.Name == "install" {
			if envName, ok := env["KAGENTI_ENV"]; ok {
				cmd = append(cmd, "--env", envName)
			}
		}

		_, err := r.Run(ctx, "bash", cmd...)
		if err != nil {
			result.Error = fmt.Errorf("script %s failed: %w", script, err)
			result.Duration = time.Since(start)
			return result
		}
	}

	result.Duration = time.Since(start)
	return result
}

// RunPhases executes multiple phases in sequence, stopping on first error.
func (r *Runner) RunPhases(ctx context.Context, repoRoot string, phases []Phase, env map[string]string) []*PhaseResult {
	var results []*PhaseResult

	for _, phase := range phases {
		fmt.Fprintf(r.Stdout, "\n=== Phase: %s — %s ===\n", phase.Name, phase.Description)
		result := r.RunPhase(ctx, repoRoot, phase, env)
		results = append(results, result)

		if result.Error != nil {
			fmt.Fprintf(r.Stderr, "Phase %s FAILED (%s): %v\n", phase.Name, result.Duration, result.Error)
			break
		}
		fmt.Fprintf(r.Stdout, "Phase %s completed (%s)\n", phase.Name, result.Duration)
	}

	return results
}

// FindRepoRoot walks up from cwd to find the repo root (has .git).
func FindRepoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("not in a git repository")
		}
		dir = parent
	}
}
