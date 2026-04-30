package cluster

import (
	"context"
	"fmt"
	"strings"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// createKind creates a Kind cluster with the kagenti config.
func (m *Manager) createKind(ctx context.Context, name string) (*Info, error) {
	if !runner.CommandExists("kind") {
		return nil, fmt.Errorf("kind not found in PATH; install from https://kind.sigs.k8s.io/")
	}

	if name == "" {
		name = "kagenti"
	}

	// Check if cluster already exists
	result, err := m.Runner.RunSilent(ctx, "kind", "get", "clusters")
	if err == nil {
		for _, existing := range strings.Split(result.Stdout, "\n") {
			if strings.TrimSpace(existing) == name {
				fmt.Fprintf(m.Stdout, "Kind cluster %q already exists\n", name)
				return &Info{
					Name:     name,
					Platform: PlatformKind,
					Context:  "kind-" + name,
					Status:   "ready",
				}, nil
			}
		}
	}

	// Find the Kind config file relative to repo root
	configPath := "deployments/ansible/kind/kind-config-registry.yaml"
	fmt.Fprintf(m.Stdout, "Creating Kind cluster %q...\n", name)

	_, err = m.Runner.Run(ctx, "kind", "create", "cluster",
		"--name", name,
		"--config", configPath,
	)
	if err != nil {
		return nil, fmt.Errorf("kind create cluster: %w", err)
	}

	info := &Info{
		Name:     name,
		Platform: PlatformKind,
		Context:  "kind-" + name,
		Status:   "ready",
	}

	fmt.Fprintf(m.Stdout, "Kind cluster %q created (context: %s)\n", name, info.Context)
	return info, nil
}

// destroyKind deletes a Kind cluster.
func (m *Manager) destroyKind(ctx context.Context, name string) error {
	if name == "" {
		name = "kagenti"
	}

	fmt.Fprintf(m.Stdout, "Deleting Kind cluster %q...\n", name)
	_, err := m.Runner.Run(ctx, "kind", "delete", "cluster", "--name", name)
	if err != nil {
		return fmt.Errorf("kind delete cluster: %w", err)
	}

	fmt.Fprintf(m.Stdout, "Kind cluster %q deleted\n", name)
	return nil
}
