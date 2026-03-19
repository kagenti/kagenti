// Package cluster provides lifecycle management for local Kubernetes clusters.
// Supports Kind, K3s (Rancher Desktop), and HyperShift hosted clusters.
package cluster

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// Platform identifies the Kubernetes platform type.
type Platform string

const (
	PlatformKind           Platform = "kind"
	PlatformK3s            Platform = "k3s"
	PlatformRancherDesktop Platform = "rancher-desktop"
	PlatformHyperShift     Platform = "hypershift"
	PlatformExisting       Platform = "existing"
)

// Info holds metadata about a cluster.
type Info struct {
	Name       string   `yaml:"name"`
	Platform   Platform `yaml:"platform"`
	Context    string   `yaml:"context"`
	Kubeconfig string   `yaml:"kubeconfig"`
	Status     string   `yaml:"status"` // ready, not-ready, unknown
}

// Manager handles cluster lifecycle operations.
type Manager struct {
	Runner runner.Executor
	Stdout io.Writer
	Stderr io.Writer
}

// NewManager creates a cluster manager with default stdout/stderr.
func NewManager() *Manager {
	return &Manager{
		Runner: runner.New(),
		Stdout: os.Stdout,
		Stderr: os.Stderr,
	}
}

// Detect identifies the current cluster platform from kubectl context.
func (m *Manager) Detect(ctx context.Context) (Platform, error) {
	result, err := m.Runner.RunSilent(ctx, "kubectl", "config", "current-context")
	if err != nil {
		return "", fmt.Errorf("no kubectl context: %w", err)
	}
	context := strings.TrimSpace(result.Stdout)

	switch {
	case strings.HasPrefix(context, "kind-"):
		return PlatformKind, nil
	case context == "rancher-desktop":
		return PlatformRancherDesktop, nil
	case strings.Contains(context, "hypershift") || strings.Contains(context, "hcp"):
		return PlatformHyperShift, nil
	default:
		return PlatformExisting, nil
	}
}

// Create creates a new cluster for the given platform.
func (m *Manager) Create(ctx context.Context, platform Platform, name string) (*Info, error) {
	switch platform {
	case PlatformKind:
		return m.createKind(ctx, name)
	case PlatformK3s, PlatformRancherDesktop:
		return m.prepareK3s(ctx)
	case PlatformHyperShift:
		return nil, fmt.Errorf("hypershift cluster creation not yet implemented in TUI; use: ./.github/scripts/hypershift/create-cluster.sh")
	default:
		return nil, fmt.Errorf("unsupported platform: %s", platform)
	}
}

// Destroy destroys a cluster.
func (m *Manager) Destroy(ctx context.Context, info *Info) error {
	switch info.Platform {
	case PlatformKind:
		return m.destroyKind(ctx, info.Name)
	case PlatformK3s, PlatformRancherDesktop:
		fmt.Fprintln(m.Stdout, "K3s cluster is managed by Rancher Desktop. Use: rdctl kubernetes reset")
		return nil
	case PlatformHyperShift:
		return fmt.Errorf("hypershift cluster destruction not yet implemented in TUI; use: ./.github/scripts/hypershift/destroy-cluster.sh")
	default:
		return fmt.Errorf("unsupported platform: %s", info.Platform)
	}
}

// List returns all known clusters.
func (m *Manager) List(ctx context.Context) ([]Info, error) {
	var clusters []Info

	// Kind clusters
	if runner.CommandExists("kind") {
		result, err := m.Runner.RunSilent(ctx, "kind", "get", "clusters")
		if err == nil && result.Stdout != "" {
			for _, name := range strings.Split(result.Stdout, "\n") {
				name = strings.TrimSpace(name)
				if name == "" {
					continue
				}
				clusters = append(clusters, Info{
					Name:     name,
					Platform: PlatformKind,
					Context:  "kind-" + name,
					Status:   "ready",
				})
			}
		}
	}

	// Rancher Desktop / K3s
	if runner.CommandExists("rdctl") {
		result, err := m.Runner.RunSilent(ctx, "kubectl", "--context", "rancher-desktop", "get", "nodes", "--no-headers")
		if err == nil && result.Stdout != "" {
			clusters = append(clusters, Info{
				Name:     "rancher-desktop",
				Platform: PlatformRancherDesktop,
				Context:  "rancher-desktop",
				Status:   "ready",
			})
		}
	}

	// HyperShift clusters from ~/clusters/hcp/
	hcpDir := filepath.Join(homeDir(), "clusters", "hcp")
	if entries, err := os.ReadDir(hcpDir); err == nil {
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			kcPath := filepath.Join(hcpDir, e.Name(), "auth", "kubeconfig")
			if _, err := os.Stat(kcPath); err == nil {
				status := "unknown"
				result, err := m.Runner.RunSilent(ctx, "kubectl", "--kubeconfig", kcPath, "get", "nodes", "--no-headers")
				if err == nil && result.Stdout != "" {
					status = "ready"
				}
				clusters = append(clusters, Info{
					Name:       e.Name(),
					Platform:   PlatformHyperShift,
					Kubeconfig: kcPath,
					Status:     status,
				})
			}
		}
	}

	// Local clusters from ~/clusters/local/
	localDir := filepath.Join(homeDir(), "clusters", "local")
	if entries, err := os.ReadDir(localDir); err == nil {
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			kcPath := filepath.Join(localDir, e.Name(), "auth", "kubeconfig")
			if _, err := os.Stat(kcPath); err == nil {
				// Skip if already listed (e.g., rancher-desktop)
				already := false
				for _, c := range clusters {
					if c.Name == e.Name() {
						already = true
						break
					}
				}
				if !already {
					clusters = append(clusters, Info{
						Name:       e.Name(),
						Platform:   PlatformExisting,
						Kubeconfig: kcPath,
						Status:     "unknown",
					})
				}
			}
		}
	}

	return clusters, nil
}

// Use sets the kubectl context to the given cluster.
func (m *Manager) Use(ctx context.Context, info *Info) error {
	if info.Kubeconfig != "" {
		fmt.Fprintf(m.Stdout, "export KUBECONFIG=%s\n", info.Kubeconfig)
		os.Setenv("KUBECONFIG", info.Kubeconfig)
		return nil
	}
	if info.Context != "" {
		_, err := m.Runner.RunSilent(ctx, "kubectl", "config", "use-context", info.Context)
		return err
	}
	return fmt.Errorf("cluster %q has no context or kubeconfig", info.Name)
}

// SaveKubeconfig saves the cluster's kubeconfig to ~/clusters/local/<name>/auth/kubeconfig.
func (m *Manager) SaveKubeconfig(ctx context.Context, info *Info) (string, error) {
	dir := filepath.Join(homeDir(), "clusters", "local", info.Name, "auth")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	kcPath := filepath.Join(dir, "kubeconfig")

	if info.Context != "" {
		result, err := m.Runner.RunSilent(ctx, "kubectl", "config", "view", "--context", info.Context, "--minify", "--raw")
		if err != nil {
			return "", err
		}
		if err := os.WriteFile(kcPath, []byte(result.Stdout), 0o600); err != nil {
			return "", err
		}
	}

	info.Kubeconfig = kcPath
	return kcPath, nil
}

func homeDir() string {
	h, _ := os.UserHomeDir()
	return h
}
