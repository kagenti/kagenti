package helm

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadValuesFile(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	path := filepath.Join(dir, "values.yaml")
	os.WriteFile(path, []byte("key: value\nnested:\n  foo: bar\n"), 0o644)

	values, err := LoadValuesFile(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if values["key"] != "value" {
		t.Errorf("expected key=value, got %v", values["key"])
	}
	nested, ok := values["nested"].(map[string]interface{})
	if !ok {
		t.Fatal("expected nested map")
	}
	if nested["foo"] != "bar" {
		t.Errorf("expected nested.foo=bar, got %v", nested["foo"])
	}
}

func TestLoadValuesFileNotFound(t *testing.T) {
	t.Parallel()
	_, err := LoadValuesFile("/nonexistent/values.yaml")
	if err == nil {
		t.Error("expected error for missing file")
	}
}

func TestLoadValuesFileInvalidYAML(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	path := filepath.Join(dir, "bad.yaml")
	os.WriteFile(path, []byte("{{invalid yaml"), 0o644)

	_, err := LoadValuesFile(path)
	if err == nil {
		t.Error("expected error for invalid YAML")
	}
}

func TestMergeValues(t *testing.T) {
	t.Parallel()
	base := map[string]interface{}{
		"a": "base-a",
		"b": "base-b",
		"nested": map[string]interface{}{
			"x": "base-x",
			"y": "base-y",
		},
	}
	overlay := map[string]interface{}{
		"b": "overlay-b",
		"c": "overlay-c",
		"nested": map[string]interface{}{
			"y": "overlay-y",
			"z": "overlay-z",
		},
	}

	result := MergeValues(base, overlay)

	if result["a"] != "base-a" {
		t.Errorf("a should be base-a, got %v", result["a"])
	}
	if result["b"] != "overlay-b" {
		t.Errorf("b should be overlay-b, got %v", result["b"])
	}
	if result["c"] != "overlay-c" {
		t.Errorf("c should be overlay-c, got %v", result["c"])
	}

	nested := result["nested"].(map[string]interface{})
	if nested["x"] != "base-x" {
		t.Errorf("nested.x should be base-x, got %v", nested["x"])
	}
	if nested["y"] != "overlay-y" {
		t.Errorf("nested.y should be overlay-y, got %v", nested["y"])
	}
	if nested["z"] != "overlay-z" {
		t.Errorf("nested.z should be overlay-z, got %v", nested["z"])
	}
}

func TestMergeValuesEmpty(t *testing.T) {
	t.Parallel()
	result := MergeValues(map[string]interface{}{})
	if len(result) != 0 {
		t.Error("merging empty maps should give empty result")
	}
}

func TestResolveEnvValues(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	envDir := filepath.Join(dir, "deployments", "envs")
	os.MkdirAll(envDir, 0o755)
	os.WriteFile(filepath.Join(envDir, "dev_values.yaml"), []byte("env: dev\n"), 0o644)

	values, err := ResolveEnvValues(dir, "dev")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if values["env"] != "dev" {
		t.Errorf("expected env=dev, got %v", values["env"])
	}
}

func TestResolveEnvValuesUnknown(t *testing.T) {
	t.Parallel()
	_, err := ResolveEnvValues("/tmp", "unknown")
	if err == nil {
		t.Error("expected error for unknown env")
	}
}

func TestResolveSecretValuesNotFound(t *testing.T) {
	t.Parallel()
	values, err := ResolveSecretValues(t.TempDir())
	if err != nil {
		t.Fatalf("missing secret file should not error: %v", err)
	}
	if values != nil {
		t.Error("missing secret file should return nil")
	}
}
