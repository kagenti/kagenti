package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadDefaults(t *testing.T) {
	t.Parallel()
	cfg := Load()
	if cfg == nil {
		t.Fatal("Load should never return nil")
	}
}

func TestSaveAndLoad(t *testing.T) {
	// Cannot use t.Parallel() with t.Setenv
	tmpDir := t.TempDir()
	t.Setenv("HOME", tmpDir)

	cfg := &Config{
		DefaultPlatform: "kind",
		LastTest: &TestResult{
			Platform:  "kind",
			Passed:    true,
			Timestamp: "2026-03-19T10:00:00Z",
			Deps: []DepBuild{
				{Repo: "kagenti/kagenti-extensions", Ref: "main", Commit: "abc123"},
			},
		},
	}

	if err := cfg.Save(); err != nil {
		t.Fatalf("Save failed: %v", err)
	}

	// Verify file exists
	cfgPath := filepath.Join(tmpDir, ".config", "kagenti", "admin.yaml")
	if _, err := os.Stat(cfgPath); err != nil {
		t.Fatalf("config file not created: %v", err)
	}

	// Load and verify
	loaded := Load()
	if loaded.DefaultPlatform != "kind" {
		t.Errorf("DefaultPlatform: got %q, want %q", loaded.DefaultPlatform, "kind")
	}
	if loaded.LastTest == nil {
		t.Fatal("LastTest should not be nil")
	}
	if !loaded.LastTest.Passed {
		t.Error("LastTest.Passed should be true")
	}
	if len(loaded.LastTest.Deps) != 1 {
		t.Errorf("expected 1 dep, got %d", len(loaded.LastTest.Deps))
	}
	if loaded.LastTest.Deps[0].Commit != "abc123" {
		t.Errorf("dep commit: got %q, want %q", loaded.LastTest.Deps[0].Commit, "abc123")
	}
}

func TestDepBuildStruct(t *testing.T) {
	t.Parallel()
	db := DepBuild{
		Repo:   "kagenti/kagenti-extensions",
		Ref:    "main",
		Commit: "a5607f9",
	}
	if db.Repo != "kagenti/kagenti-extensions" {
		t.Error("Repo mismatch")
	}
}
