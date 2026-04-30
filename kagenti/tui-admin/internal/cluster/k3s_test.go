package cluster

import (
	"bytes"
	"context"
	"testing"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

func TestPrepareK3s(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "lima-rancher-desktop Ready control-plane"}, nil
	})
	mock.On("rdctl", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})

	var buf bytes.Buffer
	m := &Manager{Runner: mock, Stdout: &buf, Stderr: &bytes.Buffer{}}

	info, err := m.prepareK3s(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Platform != PlatformRancherDesktop {
		t.Errorf("platform: got %v, want RancherDesktop", info.Platform)
	}
	if info.Context != "rancher-desktop" {
		t.Errorf("context: got %q, want rancher-desktop", info.Context)
	}

	// Verify VM fixes were called
	if !mock.CalledWith("rdctl", "make-shared") {
		t.Error("expected mount --make-shared to be called")
	}
	if !mock.CalledWith("rdctl", "inotify") {
		t.Error("expected inotify sysctl to be called")
	}
	if !mock.CalledWith("kubectl", "traefik") {
		t.Error("expected traefik scale to be called")
	}
}

func TestPrepareK3sClusterNotRunning(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "", 1)

	m := &Manager{Runner: mock, Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}}

	_, err := m.prepareK3s(context.Background())
	if err == nil {
		t.Error("expected error when cluster not running")
	}
}

func TestConfigureK3sRegistry(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "10.43.0.100"}, nil
	})
	mock.On("rdctl", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})

	var buf bytes.Buffer
	m := &Manager{Runner: mock, Stdout: &buf, Stderr: &bytes.Buffer{}}

	err := m.ConfigureK3sRegistry(context.Background(), "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify registry config was written
	if !mock.CalledWith("rdctl", "registries.yaml") {
		t.Error("expected registries.yaml to be written")
	}
	if !mock.CalledWith("rdctl", "daemon.json") {
		t.Error("expected daemon.json to be written")
	}
	if !mock.CalledWith("rdctl", "docker") {
		t.Error("expected docker restart")
	}
	if !mock.CalledWith("rdctl", "k3s") {
		t.Error("expected k3s restart")
	}
}

func TestConfigureK3sRegistryWithIP(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("rdctl", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})

	var buf bytes.Buffer
	m := &Manager{Runner: mock, Stdout: &buf, Stderr: &bytes.Buffer{}}

	err := m.ConfigureK3sRegistry(context.Background(), "10.0.0.1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !bytes.Contains(buf.Bytes(), []byte("10.0.0.1")) {
		t.Error("expected output to contain the provided IP")
	}
}
