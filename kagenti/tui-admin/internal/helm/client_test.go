package helm

import (
	"fmt"
	"testing"

	"helm.sh/helm/v3/pkg/release"
)

func TestMockClientInstallOrUpgrade(t *testing.T) {
	t.Parallel()
	mock := &MockClient{}

	rel, err := mock.InstallOrUpgrade("test-release", "/charts/test", "ns", nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rel.Name != "test-release" {
		t.Errorf("name: got %q, want test-release", rel.Name)
	}
	if len(mock.InstallCalls) != 1 {
		t.Errorf("expected 1 call, got %d", len(mock.InstallCalls))
	}
}

func TestMockClientInstallError(t *testing.T) {
	t.Parallel()
	mock := &MockClient{Err: fmt.Errorf("install failed")}

	_, err := mock.InstallOrUpgrade("test", "/charts", "ns", nil)
	if err == nil {
		t.Error("expected error")
	}
}

func TestMockClientUninstall(t *testing.T) {
	t.Parallel()
	mock := &MockClient{}
	if err := mock.Uninstall("test", "ns"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestMockClientList(t *testing.T) {
	t.Parallel()
	mock := &MockClient{
		Releases: []*release.Release{
			{Name: "kagenti", Namespace: "kagenti-system"},
			{Name: "kagenti-deps", Namespace: "kagenti-system"},
		},
	}

	releases, err := mock.List("kagenti-system")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(releases) != 2 {
		t.Errorf("expected 2 releases, got %d", len(releases))
	}
}

func TestNewClient(t *testing.T) {
	t.Parallel()
	c := NewClient("")
	if c.Settings == nil {
		t.Error("Settings should not be nil")
	}
	if c.Stdout == nil {
		t.Error("Stdout should not be nil")
	}
}

func TestNewClientWithKubeconfig(t *testing.T) {
	t.Parallel()
	c := NewClient("/tmp/test-kubeconfig")
	if c.Kubeconfig != "/tmp/test-kubeconfig" {
		t.Errorf("kubeconfig: got %q", c.Kubeconfig)
	}
	if c.Settings.KubeConfig != "/tmp/test-kubeconfig" {
		t.Errorf("settings kubeconfig: got %q", c.Settings.KubeConfig)
	}
}

func TestInterfaceCompliance(t *testing.T) {
	t.Parallel()
	// Compile-time check that both Client and MockClient implement Interface
	var _ Interface = (*Client)(nil)
	var _ Interface = (*MockClient)(nil)
}
