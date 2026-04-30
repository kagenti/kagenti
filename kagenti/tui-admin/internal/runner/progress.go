package runner

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"
)

// PhaseReporter tracks and displays progress of multi-phase execution.
type PhaseReporter struct {
	Writer  io.Writer
	Phases  []Phase
	Results []*PhaseResult
	start   time.Time
}

// NewPhaseReporter creates a reporter for the given phases.
func NewPhaseReporter(w io.Writer, phases []Phase) *PhaseReporter {
	return &PhaseReporter{
		Writer: w,
		Phases: phases,
		start:  time.Now(),
	}
}

// BeginPhase marks a phase as starting.
func (pr *PhaseReporter) BeginPhase(idx int) {
	if idx >= len(pr.Phases) {
		return
	}
	phase := pr.Phases[idx]
	fmt.Fprintf(pr.Writer, "\n")
	pr.printProgress(idx)
	fmt.Fprintf(pr.Writer, "\n  %s — %s\n", phase.Name, phase.Description)
}

// EndPhase records the result and updates the display.
func (pr *PhaseReporter) EndPhase(result *PhaseResult) {
	pr.Results = append(pr.Results, result)

	status := "PASS"
	if result.Error != nil {
		status = "FAIL"
	}

	fmt.Fprintf(pr.Writer, "  %s %s (%s)\n", status, result.Phase.Name, result.Duration.Round(time.Millisecond))
}

// Summary prints the final summary.
func (pr *PhaseReporter) Summary() {
	elapsed := time.Since(pr.start)
	passed := 0
	failed := 0
	for _, r := range pr.Results {
		if r.Error != nil {
			failed++
		} else {
			passed++
		}
	}

	fmt.Fprintf(pr.Writer, "\n")
	fmt.Fprintf(pr.Writer, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
	if failed == 0 {
		fmt.Fprintf(pr.Writer, "  PASSED  %d/%d phases (%s)\n", passed, passed+failed, elapsed.Round(time.Second))
	} else {
		fmt.Fprintf(pr.Writer, "  FAILED  %d passed, %d failed (%s)\n", passed, failed, elapsed.Round(time.Second))
	}
	fmt.Fprintf(pr.Writer, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

	// Show each phase result
	for _, r := range pr.Results {
		icon := "  pass"
		if r.Error != nil {
			icon = "  FAIL"
		}
		fmt.Fprintf(pr.Writer, "%s  %-20s  %s\n", icon, r.Phase.Name, r.Duration.Round(time.Millisecond))
	}

	// Show phases that didn't run
	completed := len(pr.Results)
	for i := completed; i < len(pr.Phases); i++ {
		fmt.Fprintf(pr.Writer, "  skip  %-20s\n", pr.Phases[i].Name)
	}
	fmt.Fprintf(pr.Writer, "\n")
}

// printProgress shows the phase checklist with current state.
func (pr *PhaseReporter) printProgress(currentIdx int) {
	var parts []string
	for i, phase := range pr.Phases {
		switch {
		case i < len(pr.Results):
			if pr.Results[i].Error != nil {
				parts = append(parts, fmt.Sprintf("X %s", phase.Name))
			} else {
				parts = append(parts, fmt.Sprintf("v %s", phase.Name))
			}
		case i == currentIdx:
			parts = append(parts, fmt.Sprintf("> %s", phase.Name))
		default:
			parts = append(parts, fmt.Sprintf("  %s", phase.Name))
		}
	}
	fmt.Fprintf(pr.Writer, "  [%s]\n", strings.Join(parts, " | "))
}

// RunPhasesWithProgress executes phases with live progress reporting.
func (r *Runner) RunPhasesWithProgress(w io.Writer, repoRoot string, phases []Phase, env map[string]string) []*PhaseResult {
	reporter := NewPhaseReporter(w, phases)

	for i, phase := range phases {
		reporter.BeginPhase(i)
		result := r.RunPhase(context.Background(), repoRoot, phase, env)
		reporter.EndPhase(result)

		if result.Error != nil {
			reporter.Summary()
			return reporter.Results
		}
	}

	reporter.Summary()
	return reporter.Results
}
