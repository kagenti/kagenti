package cluster

import (
	"context"
	"fmt"
	"time"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

// prepareK3s verifies and prepares a Rancher Desktop K3s cluster for Kagenti.
func (m *Manager) prepareK3s(ctx context.Context) (*Info, error) {
	if !runner.CommandExists("rdctl") {
		return nil, fmt.Errorf("rdctl not found in PATH; install Rancher Desktop from https://rancherdesktop.io/")
	}

	// Verify cluster is running
	result, err := m.Runner.RunSilent(ctx, "kubectl", "--context", "rancher-desktop", "get", "nodes", "--no-headers")
	if err != nil {
		return nil, fmt.Errorf("rancher Desktop K3s cluster not running: %w\nStart Rancher Desktop first", err)
	}
	fmt.Fprintf(m.Stdout, "K3s node: %s\n", result.Stdout)

	// Fix mount propagation for Istio CNI
	fmt.Fprintln(m.Stdout, "Preparing VM for Istio...")
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "mount", "--make-shared", "/run")

	// Fix inotify limits
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "sysctl", "-w", "fs.inotify.max_user_instances=1024")
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "sysctl", "-w", "fs.inotify.max_user_watches=524288")

	// Disable Traefik (Istio Gateway replaces it)
	fmt.Fprintln(m.Stdout, "Disabling Traefik (Istio Gateway replaces it)...")
	m.Runner.RunSilent(ctx, "kubectl", "--context", "rancher-desktop", "-n", "kube-system", "scale", "deploy", "traefik", "--replicas=0")

	info := &Info{
		Name:     "rancher-desktop",
		Platform: PlatformRancherDesktop,
		Context:  "rancher-desktop",
		Status:   "ready",
	}

	return info, nil
}

// ConfigureK3sRegistry sets up the in-cluster registry mirror for K3s/Docker.
// Must be called after the registry service is deployed (post-platform-install).
func (m *Manager) ConfigureK3sRegistry(ctx context.Context, registryIP string) error {
	if registryIP == "" {
		result, err := m.Runner.RunSilent(ctx, "kubectl", "get", "svc", "-n", "cr-system", "registry",
			"-o", "jsonpath={.spec.clusterIP}")
		if err != nil {
			return fmt.Errorf("registry service not found: %w", err)
		}
		registryIP = result.Stdout
	}

	fmt.Fprintf(m.Stdout, "Configuring K3s registry mirror (ClusterIP: %s)...\n", registryIP)

	// 1. Add DNS entry for Docker daemon
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "sh", "-c",
		fmt.Sprintf("grep -q registry.cr-system.svc.cluster.local /etc/hosts || echo '%s registry.cr-system.svc.cluster.local' >> /etc/hosts", registryIP))

	// 2. K3s registries.yaml
	registriesYAML := fmt.Sprintf(`mirrors:
  "registry.cr-system.svc.cluster.local:5000":
    endpoint:
      - "http://%s:5000"
configs:
  "registry.cr-system.svc.cluster.local:5000":
    tls:
      insecure_skip_verify: true
`, registryIP)

	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "sh", "-c",
		fmt.Sprintf("cat > /etc/rancher/k3s/registries.yaml << 'EOF'\n%sEOF", registriesYAML))

	// 3. Docker daemon insecure registries
	daemonJSON := fmt.Sprintf(`{
  "min-api-version": "1.41",
  "features": { "containerd-snapshotter": true },
  "insecure-registries": ["registry.cr-system.svc.cluster.local:5000", "%s:5000"]
}`, registryIP)

	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "sh", "-c",
		fmt.Sprintf("cat > /etc/docker/daemon.json << 'EOF'\n%sEOF", daemonJSON))

	// 4. Restart Docker + K3s
	fmt.Fprintln(m.Stdout, "Restarting Docker + K3s to apply registry config...")
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "rc-service", "docker", "restart")
	time.Sleep(3 * time.Second)
	m.Runner.RunSilent(ctx, "rdctl", "shell", "--", "sudo", "rc-service", "k3s", "restart")

	// Wait for K3s to come back
	for i := 0; i < 30; i++ {
		if _, err := m.Runner.RunSilent(ctx, "kubectl", "get", "nodes"); err == nil {
			break
		}
		time.Sleep(2 * time.Second)
	}

	fmt.Fprintln(m.Stdout, "K3s + Docker restarted with registry config")
	return nil
}
