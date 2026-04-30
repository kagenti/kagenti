package cluster

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/runner"
)

func newTestManager(mock *runner.MockExecutor) *Manager {
	return &Manager{
		Runner: mock,
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
	}
}

func TestDetectKind(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "kind-kagenti", 0)
	m := newTestManager(mock)

	p, err := m.Detect(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if p != PlatformKind {
		t.Errorf("expected Kind, got %v", p)
	}
}

func TestDetectRancherDesktop(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "rancher-desktop", 0)
	m := newTestManager(mock)

	p, err := m.Detect(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if p != PlatformRancherDesktop {
		t.Errorf("expected RancherDesktop, got %v", p)
	}
}

func TestDetectHyperShift(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "api-kagenti-team-hypershift", 0)
	m := newTestManager(mock)

	p, err := m.Detect(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if p != PlatformHyperShift {
		t.Errorf("expected HyperShift, got %v", p)
	}
}

func TestDetectExisting(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "some-other-context", 0)
	m := newTestManager(mock)

	p, err := m.Detect(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if p != PlatformExisting {
		t.Errorf("expected Existing, got %v", p)
	}
}

func TestDetectNoContext(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "", 1)
	m := newTestManager(mock)

	_, err := m.Detect(context.Background())
	if err == nil {
		t.Error("expected error when no context")
	}
}

func TestCreateKind(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	// kind get clusters returns empty (no existing clusters)
	mock.On("kind", func(args []string) (*runner.Result, error) {
		if len(args) > 0 && args[0] == "get" {
			return &runner.Result{Stdout: ""}, nil
		}
		// kind create cluster
		return &runner.Result{}, nil
	})
	mock.On("bash", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})
	m := newTestManager(mock)

	info, err := m.Create(context.Background(), PlatformKind, "test")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Name != "test" {
		t.Errorf("name: got %q, want %q", info.Name, "test")
	}
	if info.Platform != PlatformKind {
		t.Errorf("platform: got %v, want Kind", info.Platform)
	}
	if info.Context != "kind-test" {
		t.Errorf("context: got %q, want %q", info.Context, "kind-test")
	}
}

func TestCreateKindExists(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kind", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "test\nother"}, nil
	})
	m := newTestManager(mock)

	info, err := m.Create(context.Background(), PlatformKind, "test")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Status != "ready" {
		t.Errorf("existing cluster should be ready, got %q", info.Status)
	}
}

func TestCreateK3s(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kubectl", func(args []string) (*runner.Result, error) {
		return &runner.Result{Stdout: "lima-rancher-desktop Ready control-plane"}, nil
	})
	mock.On("rdctl", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})
	m := newTestManager(mock)

	info, err := m.Create(context.Background(), PlatformRancherDesktop, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Platform != PlatformRancherDesktop {
		t.Errorf("platform: got %v, want RancherDesktop", info.Platform)
	}
	if info.Context != "rancher-desktop" {
		t.Errorf("context: got %q, want rancher-desktop", info.Context)
	}
}

func TestCreateUnsupported(t *testing.T) {
	t.Parallel()
	m := newTestManager(runner.NewMockExecutor())
	_, err := m.Create(context.Background(), "unsupported", "")
	if err == nil {
		t.Error("expected error for unsupported platform")
	}
}

func TestDestroyKind(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.On("kind", func(args []string) (*runner.Result, error) {
		return &runner.Result{}, nil
	})
	m := newTestManager(mock)

	err := m.Destroy(context.Background(), &Info{Name: "test", Platform: PlatformKind})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !mock.Called("kind") {
		t.Error("expected kind delete to be called")
	}
}

func TestDestroyK3s(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	m := &Manager{Runner: runner.NewMockExecutor(), Stdout: &buf, Stderr: &bytes.Buffer{}}

	err := m.Destroy(context.Background(), &Info{Name: "rd", Platform: PlatformRancherDesktop})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("Rancher Desktop")) {
		t.Error("expected Rancher Desktop message")
	}
}

func TestDestroyHyperShift(t *testing.T) {
	t.Parallel()
	m := newTestManager(runner.NewMockExecutor())
	err := m.Destroy(context.Background(), &Info{Name: "hcp", Platform: PlatformHyperShift})
	if err == nil {
		t.Error("expected error for HyperShift destroy (not implemented)")
	}
}

func TestUseWithKubeconfig(t *testing.T) {
	t.Parallel()
	m := newTestManager(runner.NewMockExecutor())
	info := &Info{Name: "test", Kubeconfig: "/tmp/test-kubeconfig"}

	err := m.Use(context.Background(), info)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestUseWithContext(t *testing.T) {
	t.Parallel()
	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "", 0)
	m := newTestManager(mock)
	info := &Info{Name: "test", Context: "kind-test"}

	err := m.Use(context.Background(), info)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !mock.Called("kubectl") {
		t.Error("expected kubectl config use-context to be called")
	}
}

func TestUseNoContextOrKubeconfig(t *testing.T) {
	t.Parallel()
	m := newTestManager(runner.NewMockExecutor())
	err := m.Use(context.Background(), &Info{Name: "test"})
	if err == nil {
		t.Error("expected error when no context or kubeconfig")
	}
}

func TestListDoesNotPanic(t *testing.T) {
	t.Parallel()
	m := NewManager()
	m.Stdout = &bytes.Buffer{}
	m.Stderr = &bytes.Buffer{}

	clusters, err := m.List(context.Background())
	if err != nil {
		t.Fatalf("List should not return error: %v", err)
	}
	t.Logf("Found %d clusters", len(clusters))
}

func TestSaveKubeconfig(t *testing.T) {
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	mock := runner.NewMockExecutor()
	mock.OnResult("kubectl", "apiVersion: v1\nclusters: []\nkind: Config", 0)
	m := &Manager{Runner: mock, Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}}

	info := &Info{Name: "test-cluster", Platform: PlatformKind, Context: "kind-test"}

	kcPath, err := m.SaveKubeconfig(context.Background(), info)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if kcPath == "" {
		t.Error("expected non-empty kubeconfig path")
	}

	// Verify the file was written
	data, err := os.ReadFile(kcPath)
	if err != nil {
		t.Fatalf("kubeconfig file not created: %v", err)
	}
	if !bytes.Contains(data, []byte("apiVersion")) {
		t.Error("kubeconfig content doesn't look right")
	}

	// Verify directory structure
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
}
