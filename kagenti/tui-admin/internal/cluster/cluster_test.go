package cluster

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

func TestDetectPlatform(t *testing.T) {
	t.Parallel()
	// This test verifies Detect doesn't panic — actual detection depends on
	// the host's kubectl config, so we just verify it returns a valid value.
	m := NewManager()
	m.Runner = &runner.Runner{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}

	platform, err := m.Detect(context.Background())
	// It's OK if there's no context configured — we just test that it doesn't panic
	if err != nil {
		t.Logf("Detect returned error (expected if no kubectl): %v", err)
		return
	}

	validPlatforms := map[Platform]bool{
		PlatformKind:           true,
		PlatformRancherDesktop: true,
		PlatformHyperShift:     true,
		PlatformExisting:       true,
	}
	if !validPlatforms[platform] {
		t.Errorf("unexpected platform: %v", platform)
	}
}

func TestListDoesNotPanic(t *testing.T) {
	t.Parallel()
	m := NewManager()
	m.Runner = &runner.Runner{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}

	// List should never panic, even if no clusters exist
	clusters, err := m.List(context.Background())
	if err != nil {
		t.Fatalf("List should not return error: %v", err)
	}
	t.Logf("Found %d clusters", len(clusters))
}

func TestSaveKubeconfig(t *testing.T) {
	// Cannot use t.Parallel() with t.Setenv
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	m := NewManager()
	m.Runner = &runner.Runner{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}

	info := &Info{
		Name:     "test-cluster",
		Platform: PlatformKind,
		Context:  "kind-test-cluster",
	}

	// SaveKubeconfig will fail because kubectl isn't pointed at a real cluster,
	// but the directory creation should work
	_, err := m.SaveKubeconfig(context.Background(), info)
	if err != nil {
		t.Logf("SaveKubeconfig error (expected - no real cluster): %v", err)
	}

	// Verify the directory was created
	dir := filepath.Join(tmpDir, "clusters", "local", "test-cluster", "auth")
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		t.Error("expected directory to be created")
	}
}

func TestPlatformConstants(t *testing.T) {
	t.Parallel()
	if PlatformKind != "kind" {
		t.Error("PlatformKind should be 'kind'")
	}
	if PlatformK3s != "k3s" {
		t.Error("PlatformK3s should be 'k3s'")
	}
	if PlatformRancherDesktop != "rancher-desktop" {
		t.Error("PlatformRancherDesktop should be 'rancher-desktop'")
	}
	if PlatformHyperShift != "hypershift" {
		t.Error("PlatformHyperShift should be 'hypershift'")
	}
}

func TestInfoStruct(t *testing.T) {
	t.Parallel()
	info := Info{
		Name:     "test",
		Platform: PlatformKind,
		Context:  "kind-test",
		Status:   "ready",
	}
	if info.Name != "test" {
		t.Error("Name mismatch")
	}
	if info.Platform != PlatformKind {
		t.Error("Platform mismatch")
	}
}
