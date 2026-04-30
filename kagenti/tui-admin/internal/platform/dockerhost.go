package platform

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"time"
)

// ConfigureDockerhost creates the dockerhost EndpointSlice and Service
// for Ollama access from pods. Uses host.docker.internal to find the host IP.
//
// Security: Only exposes port 11434 (Ollama). A NetworkPolicy restricts
// egress to that port. This is for LOCAL DEV ONLY.
func (inst *Installer) ConfigureDockerhost(ctx context.Context) error {
	if inst.K8s == nil {
		return fmt.Errorf("k8s client not initialized")
	}

	// Discover host IP via host.docker.internal from inside a pod.
	// This works on Docker Desktop and Rancher Desktop (macOS/Windows).
	// On Linux with plain Docker, falls back to node InternalIP.
	hostIP, err := inst.discoverHostIP(ctx)
	if err != nil {
		return fmt.Errorf("discover host IP for Ollama: %w", err)
	}

	fmt.Fprintf(inst.Stdout, "Configuring dockerhost (host IP: %s, port: 11434)...\n", hostIP)

	// Create EndpointSlice + headless Service + NetworkPolicy in team1
	manifests := fmt.Sprintf(`apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: dockerhost
  namespace: team1
  labels:
    kubernetes.io/service-name: dockerhost
addressType: IPv4
endpoints:
- addresses:
  - %s
  conditions:
    ready: true
ports:
- name: ollama
  port: 11434
  protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: dockerhost
  namespace: team1
spec:
  clusterIP: None
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dockerhost-egress
  namespace: team1
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: %s/32
    ports:
    - port: 11434
      protocol: TCP`, hostIP, hostIP)

	// Apply via kubectl (client-go Apply requires server-side apply setup)
	return execCommand(ctx, inst.Stdout, "kubectl", "apply", "-f", "-", "--input="+manifests)
}

// discoverHostIP finds the host machine IP reachable from inside pods.
func (inst *Installer) discoverHostIP(ctx context.Context) (string, error) {
	// Try host.docker.internal first (works on Docker Desktop, Rancher Desktop)
	// We resolve it from inside a pod via kubectl run
	result, err := execCommandOutput(ctx, "kubectl", "run", "--rm", "-i",
		"--restart=Never", "--image=busybox:1.36",
		fmt.Sprintf("detect-host-%d", randomInt()),
		"--timeout=30s", "--",
		"sh", "-c", "nslookup host.docker.internal 2>/dev/null | grep -A1 'Name:' | grep 'Address:' | awk '{print $2}'")

	if err == nil {
		ip := strings.TrimSpace(result)
		if isIPv4(ip) {
			return ip, nil
		}
	}

	// Fallback: node ExternalIP
	if inst.K8s != nil {
		nodes, err := inst.K8s.GetNodes(ctx)
		if err == nil && len(nodes) > 0 {
			for _, addr := range nodes[0].Status.Addresses {
				if addr.Type == "ExternalIP" && isIPv4(addr.Address) {
					return addr.Address, nil
				}
			}
			for _, addr := range nodes[0].Status.Addresses {
				if addr.Type == "InternalIP" && isIPv4(addr.Address) {
					return addr.Address, nil
				}
			}
		}
	}

	return "", fmt.Errorf("could not discover host IP; set DOCKER_HOST_IP env var")
}

func isIPv4(s string) bool {
	parts := strings.Split(s, ".")
	if len(parts) != 4 {
		return false
	}
	for _, p := range parts {
		if p == "" {
			return false
		}
	}
	return true
}

func randomInt() int {
	return int(time.Now().UnixNano() % 100000)
}

// execCommandOutput runs a command and returns stdout as string.
func execCommandOutput(ctx context.Context, name string, args ...string) (string, error) {
	cmd := execCmd(ctx, name, args...)
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	err := cmd.Run()
	return stdout.String(), err
}
