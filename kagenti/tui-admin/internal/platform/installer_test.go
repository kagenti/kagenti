package platform

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestCreateSecrets(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	inst := &Installer{
		RepoRoot: dir,
		Stdout:   &bytes.Buffer{},
	}

	if err := inst.CreateSecrets(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	path := filepath.Join(dir, "deployments", "envs", ".secret_values.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("secret file not created: %v", err)
	}
	if !bytes.Contains(data, []byte("jwt_key")) {
		t.Error("secret file should contain jwt_key")
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

	if err := inst.CreateSecrets(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !bytes.Contains(buf.Bytes(), []byte("already exists")) {
		t.Error("should log that secrets already exist")
	}
}

func TestAllPhases(t *testing.T) {
	t.Parallel()
	inst := &Installer{Stdout: &bytes.Buffer{}}
	phases := inst.AllPhases()

	if len(phases) < 3 {
		t.Errorf("expected at least 3 phases, got %d", len(phases))
	}

	names := make(map[string]bool)
	for _, p := range phases {
		names[p.Name] = true
		if p.Fn == nil {
			t.Errorf("phase %s has nil Fn", p.Name)
		}
	}

	for _, expected := range []string{"create-secrets", "install-platform", "wait-ready"} {
		if !names[expected] {
			t.Errorf("missing phase: %s", expected)
		}
	}
}
