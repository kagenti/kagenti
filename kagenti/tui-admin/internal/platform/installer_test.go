package platform

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	helmclient "github.com/kagenti/kagenti/kagenti/tui-admin/internal/helm"
	k8sclient "github.com/kagenti/kagenti/kagenti/tui-admin/internal/k8s"
	"k8s.io/client-go/kubernetes/fake"
)

func TestCreateSecrets(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	inst := &Installer{RepoRoot: dir, Stdout: &bytes.Buffer{}}

	if err := inst.CreateSecrets(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	path := filepath.Join(dir, "deployments", "envs", ".secret_values.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("secret file not created: %v", err)
	}
	if !bytes.Contains(data, []byte("jwt_key")) {
		t.Error("should contain jwt_key")
	}
}

func TestCreateSecretsAlreadyExists(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	secretDir := filepath.Join(dir, "deployments", "envs")
	os.MkdirAll(secretDir, 0o755)
	os.WriteFile(filepath.Join(secretDir, ".secret_values.yaml"), []byte("existing"), 0o600)

	var buf bytes.Buffer
	inst := &Installer{RepoRoot: dir, Stdout: &buf}

	inst.CreateSecrets(context.Background())
	if !bytes.Contains(buf.Bytes(), []byte("already exists")) {
		t.Error("should log already exists")
	}
}

func TestAllPhases(t *testing.T) {
	t.Parallel()
	inst := &Installer{Stdout: &bytes.Buffer{}}
	phases := inst.AllPhases()
	if len(phases) < 3 {
		t.Errorf("expected at least 3 phases, got %d", len(phases))
	}
	for _, p := range phases {
		if p.Fn == nil {
			t.Errorf("phase %s has nil Fn", p.Name)
		}
	}
}

func TestInstallerRun(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	var buf bytes.Buffer
	inst := &Installer{RepoRoot: dir, Env: "dev", Stdout: &buf}

	err := inst.Run(context.Background())
	if err == nil {
		t.Error("expected error (no Ansible/k8s)")
	}
	// Secrets phase should have run before failure
	secretPath := filepath.Join(dir, "deployments", "envs", ".secret_values.yaml")
	if _, err := os.Stat(secretPath); os.IsNotExist(err) {
		t.Error("secrets should have been created before install failed")
	}
}

func TestExecCmd(t *testing.T) {
	t.Parallel()
	cmd := execCmd(context.Background(), "echo", "hello")
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("exec failed: %v", err)
	}
	if string(out) != "hello\n" {
		t.Errorf("got %q", string(out))
	}
}

func TestExecCommand(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	err := execCommand(context.Background(), &buf, "echo", "test-output")
	if err != nil {
		t.Fatalf("failed: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("test-output")) {
		t.Error("should contain test-output")
	}
}

func TestExecCommandOutput(t *testing.T) {
	t.Parallel()
	out, err := execCommandOutput(context.Background(), "echo", "captured")
	if err != nil {
		t.Fatalf("failed: %v", err)
	}
	if out != "captured\n" {
		t.Errorf("got %q", out)
	}
}

func TestWaitReadyNoClient(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	inst := &Installer{Stdout: &buf, K8s: nil}

	err := inst.WaitReady(context.Background())
	if err != nil {
		t.Fatalf("should not error with nil k8s: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("No k8s client")) {
		t.Error("should log 'No k8s client'")
	}
}

func TestWaitReadyWithFakeClient(t *testing.T) {
	t.Parallel()
	// Use a fake k8s client — WaitForNamespace will timeout on empty namespaces
	// but WaitReady should not error (it logs warnings)
	k8sFake := &k8sclient.Client{Clientset: fake.NewSimpleClientset()}

	var buf bytes.Buffer
	inst := &Installer{Stdout: &buf, K8s: k8sFake}

	// Use a short context to avoid long waits
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := inst.WaitReady(ctx)
	if err != nil {
		t.Fatalf("WaitReady should not error (logs warnings): %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("Waiting for")) {
		t.Error("should log 'Waiting for'")
	}
}

func TestInstallPlatformNoScript(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	var buf bytes.Buffer
	// Create env values so ResolveEnvValues works
	envDir := filepath.Join(dir, "deployments", "envs")
	os.MkdirAll(envDir, 0o755)
	os.WriteFile(filepath.Join(envDir, "dev_values.yaml"), []byte("charts: {}"), 0o644)

	inst := &Installer{
		RepoRoot: dir,
		Env:      "dev",
		Stdout:   &buf,
		Helm:     &helmclient.MockClient{},
	}

	err := inst.InstallPlatform(context.Background())
	if err == nil {
		t.Error("should fail when installer script not found")
	}
	if !bytes.Contains(buf.Bytes(), []byte("Installing platform")) {
		t.Error("should log installing")
	}
}

// TestIsIPv4 and TestRandomInt are in dockerhost_test.go
