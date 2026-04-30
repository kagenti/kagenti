// Package platform provides the Kagenti platform installation logic,
// replacing shell scripts and Ansible with native Go using Helm SDK + client-go.
package platform

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	helmclient "github.com/kagenti/kagenti/kagenti/tui-admin/internal/helm"
	k8sclient "github.com/kagenti/kagenti/kagenti/tui-admin/internal/k8s"
)

// Installer orchestrates the Kagenti platform installation.
type Installer struct {
	Helm     helmclient.Interface
	K8s      *k8sclient.Client
	RepoRoot string
	Env      string // dev, k3s, ocp
	Stdout   io.Writer
}

// NewInstaller creates an Installer from a repo root and environment.
func NewInstaller(repoRoot, env, kubeconfig string) (*Installer, error) {
	k8s, err := k8sclient.NewClient(kubeconfig)
	if err != nil {
		return nil, fmt.Errorf("create k8s client: %w", err)
	}

	return &Installer{
		Helm:     helmclient.NewClient(kubeconfig),
		K8s:      k8s,
		RepoRoot: repoRoot,
		Env:      env,
		Stdout:   os.Stdout,
	}, nil
}

// Phase represents a named installation phase.
type Phase struct {
	Name string
	Fn   func(ctx context.Context) error
}

// AllPhases returns all installation phases in order.
func (inst *Installer) AllPhases() []Phase {
	return []Phase{
		{"create-secrets", inst.CreateSecrets},
		{"install-platform", inst.InstallPlatform},
		{"wait-ready", inst.WaitReady},
		{"configure-dockerhost", inst.ConfigureDockerhost},
	}
}

// Run executes all phases in sequence.
func (inst *Installer) Run(ctx context.Context) error {
	for _, phase := range inst.AllPhases() {
		fmt.Fprintf(inst.Stdout, "\n=== Phase: %s ===\n", phase.Name)
		start := time.Now()
		if err := phase.Fn(ctx); err != nil {
			return fmt.Errorf("phase %s failed: %w", phase.Name, err)
		}
		fmt.Fprintf(inst.Stdout, "Phase %s completed (%s)\n", phase.Name, time.Since(start).Round(time.Second))
	}
	return nil
}

// CreateSecrets creates the secret values file if it doesn't exist.
func (inst *Installer) CreateSecrets(ctx context.Context) error {
	secretFile := filepath.Join(inst.RepoRoot, "deployments", "envs", ".secret_values.yaml")
	if _, err := os.Stat(secretFile); err == nil {
		fmt.Fprintln(inst.Stdout, "Secrets file already exists, skipping")
		return nil
	}

	fmt.Fprintln(inst.Stdout, "Creating local test secrets...")
	content := `# Local secret values (for testing)
global:
  jwt_key: "local-test-jwt-key"
  db_password: "local-test-db-password"

kagenti:
  postgres:
    password: "local-test-pg-password"
`
	if err := os.MkdirAll(filepath.Dir(secretFile), 0o755); err != nil {
		return err
	}
	return os.WriteFile(secretFile, []byte(content), 0o600)
}

// InstallPlatform installs all Helm charts via the Ansible installer.
// Bridge to Ansible — will be replaced with direct Helm SDK calls.
func (inst *Installer) InstallPlatform(ctx context.Context) error {
	fmt.Fprintln(inst.Stdout, "Installing platform via Ansible...")

	values, err := helmclient.ResolveEnvValues(inst.RepoRoot, inst.Env)
	if err != nil {
		return fmt.Errorf("load env values: %w", err)
	}

	if charts, ok := values["charts"].(map[string]interface{}); ok {
		for name, v := range charts {
			if chartCfg, ok := v.(map[string]interface{}); ok {
				if enabled, _ := chartCfg["enabled"].(bool); enabled {
					fmt.Fprintf(inst.Stdout, "  Chart: %s (enabled)\n", name)
				}
			}
		}
	}

	installerScript := filepath.Join(inst.RepoRoot, "deployments", "ansible", "run-install.sh")
	if _, err := os.Stat(installerScript); err != nil {
		return fmt.Errorf("installer script not found: %s", installerScript)
	}

	cmd := fmt.Sprintf("cd %s && PATH=/opt/homebrew/opt/helm@3/bin:$PATH ./deployments/ansible/run-install.sh --env %s", inst.RepoRoot, inst.Env)
	return execCommand(ctx, inst.Stdout, "bash", "-c", cmd)
}

// WaitReady waits for all platform components to be ready.
func (inst *Installer) WaitReady(ctx context.Context) error {
	if inst.K8s == nil {
		fmt.Fprintln(inst.Stdout, "No k8s client, skipping wait")
		return nil
	}
	for _, ns := range []string{"kagenti-system", "keycloak", "istio-system", "cert-manager"} {
		fmt.Fprintf(inst.Stdout, "Waiting for %s...\n", ns)
		if err := inst.K8s.WaitForNamespace(ctx, ns, 5*time.Minute); err != nil {
			fmt.Fprintf(inst.Stdout, "Warning: %s not fully ready: %v\n", ns, err)
		} else {
			fmt.Fprintf(inst.Stdout, "  %s ready\n", ns)
		}
	}
	return nil
}

// execCommand runs a command with stdout/stderr piped.
func execCommand(ctx context.Context, w io.Writer, name string, args ...string) error {
	cmd := execCmd(ctx, name, args...)
	cmd.Stdout = w
	cmd.Stderr = w
	return cmd.Run()
}
