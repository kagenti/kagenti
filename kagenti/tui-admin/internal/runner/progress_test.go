package runner

import (
	"bytes"
	"fmt"
	"os"
	"testing"
	"time"
)

func TestPhaseReporter(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	phases := []Phase{
		{Name: "install", Description: "Install platform"},
		{Name: "deploy", Description: "Deploy agents"},
		{Name: "test", Description: "Run tests"},
	}

	reporter := NewPhaseReporter(&buf, phases)

	reporter.BeginPhase(0)
	reporter.EndPhase(&PhaseResult{Phase: phases[0], Duration: 2 * time.Second})

	reporter.BeginPhase(1)
	reporter.EndPhase(&PhaseResult{Phase: phases[1], Duration: 1 * time.Second})

	reporter.BeginPhase(2)
	reporter.EndPhase(&PhaseResult{Phase: phases[2], Duration: 3 * time.Second})

	reporter.Summary()

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("PASSED")) {
		t.Error("should show PASSED when all phases pass")
	}
	if !bytes.Contains([]byte(output), []byte("3/3")) {
		t.Error("should show 3/3 phases")
	}
}

func TestPhaseReporterWithFailure(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	phases := []Phase{
		{Name: "install", Description: "Install"},
		{Name: "test", Description: "Test"},
	}

	reporter := NewPhaseReporter(&buf, phases)

	reporter.BeginPhase(0)
	reporter.EndPhase(&PhaseResult{Phase: phases[0], Duration: 1 * time.Second})

	reporter.BeginPhase(1)
	reporter.EndPhase(&PhaseResult{
		Phase:    phases[1],
		Duration: 500 * time.Millisecond,
		Error:    fmt.Errorf("phase failed"),
	})

	reporter.Summary()

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("FAILED")) {
		t.Error("should show FAILED")
	}
	if !bytes.Contains([]byte(output), []byte("FAIL")) {
		t.Error("should show FAIL for test phase")
	}
}

func TestPhaseReporterSkipped(t *testing.T) {
	t.Parallel()
	var buf bytes.Buffer
	phases := []Phase{
		{Name: "install", Description: "Install"},
		{Name: "deploy", Description: "Deploy"},
		{Name: "test", Description: "Test"},
	}

	reporter := NewPhaseReporter(&buf, phases)

	reporter.BeginPhase(0)
	reporter.EndPhase(&PhaseResult{
		Phase:    phases[0],
		Duration: 1 * time.Second,
		Error:    fmt.Errorf("phase failed"),
	})

	// Skip remaining phases
	reporter.Summary()

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("skip")) {
		t.Error("should show skipped phases")
	}
}

func TestRunPhasesWithProgress(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()

	// Create dummy scripts
	writeScript(t, dir, "pass.sh", "#!/bin/sh\necho ok")
	writeScript(t, dir, "fail.sh", "#!/bin/sh\nexit 1")

	var buf bytes.Buffer
	r := &Runner{Stdout: &buf, Stderr: &buf}

	phases := []Phase{
		{Name: "pass", Description: "Should pass", Scripts: []string{"pass.sh"}},
	}

	results := r.RunPhasesWithProgress(&buf, dir, phases, nil)
	if len(results) != 1 {
		t.Errorf("expected 1 result, got %d", len(results))
	}
	if results[0].Error != nil {
		t.Errorf("expected pass, got error: %v", results[0].Error)
	}

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("PASSED")) {
		t.Error("should show PASSED in summary")
	}
}

func writeScript(t *testing.T, dir, name, content string) {
	t.Helper()
	path := dir + "/" + name
	if err := writeFile(path, content); err != nil {
		t.Fatal(err)
	}
}

func writeFile(path, content string) error {
	return os.WriteFile(path, []byte(content), 0o755)
}
