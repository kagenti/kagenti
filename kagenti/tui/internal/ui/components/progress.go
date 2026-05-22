package components

import (
	"fmt"
	"strings"

	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// ProgressStep represents a step in a deploy progress indicator.
type ProgressStep struct {
	Label  string
	Status string // "pending", "running", "done", "error"
}

// Progress renders a deploy progress with step indicators.
type Progress struct {
	Title string
	Steps []ProgressStep
}

// NewProgress creates a new progress indicator.
func NewProgress(title string, steps []string) Progress {
	ps := make([]ProgressStep, len(steps))
	for i, s := range steps {
		ps[i] = ProgressStep{Label: s, Status: "pending"}
	}
	return Progress{Title: title, Steps: ps}
}

// SetStep updates a step status by index.
func (p *Progress) SetStep(index int, status string) {
	if index >= 0 && index < len(p.Steps) {
		p.Steps[index].Status = status
	}
}

// View renders the progress indicator.
func (p Progress) View() string {
	var lines []string
	lines = append(lines, theme.TitleStyle.Render(p.Title))
	lines = append(lines, "")

	for _, step := range p.Steps {
		var icon string
		switch step.Status {
		case "done":
			icon = theme.SuccessStyle.Render("✓")
		case "running":
			icon = theme.WarningStyle.Render("⟳")
		case "error":
			icon = theme.ErrorStyle.Render("✗")
		default:
			icon = theme.MutedStyle.Render("○")
		}
		lines = append(lines, fmt.Sprintf("  %s %s", icon, step.Label))
	}

	return strings.Join(lines, "\n")
}
