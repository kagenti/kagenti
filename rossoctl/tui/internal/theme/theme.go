// Package theme provides shared styles and helpers for the TUI.
package theme

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

// Colors — adaptive for light/dark terminals.
var (
	ColorPrimary   = lipgloss.AdaptiveColor{Light: "#5A56E0", Dark: "#7571F9"}
	ColorSecondary = lipgloss.AdaptiveColor{Light: "#3C3C3C", Dark: "#ABABAB"}
	ColorSuccess   = lipgloss.AdaptiveColor{Light: "#00A86B", Dark: "#73D77A"}
	ColorWarning   = lipgloss.AdaptiveColor{Light: "#E69500", Dark: "#FFCC00"}
	ColorError     = lipgloss.AdaptiveColor{Light: "#E03131", Dark: "#FF6B6B"}
	ColorMuted     = lipgloss.AdaptiveColor{Light: "#999999", Dark: "#666666"}
	ColorBorder    = lipgloss.AdaptiveColor{Light: "#DDDDDD", Dark: "#444444"}
)

// Text styles.
var (
	TitleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(ColorPrimary)

	SubtitleStyle = lipgloss.NewStyle().
			Foreground(ColorSecondary)

	LabelStyle = lipgloss.NewStyle().
			Bold(true)

	ValueStyle = lipgloss.NewStyle().
			Foreground(ColorSecondary)

	MutedStyle = lipgloss.NewStyle().
			Foreground(ColorMuted)

	ErrorStyle = lipgloss.NewStyle().
			Foreground(ColorError)

	SuccessStyle = lipgloss.NewStyle().
			Foreground(ColorSuccess)

	WarningStyle = lipgloss.NewStyle().
			Foreground(ColorWarning)
)

// Layout styles.
var (
	StatusBarStyle = lipgloss.NewStyle().
			Padding(0, 1).
			Background(lipgloss.AdaptiveColor{Light: "#F0F0F0", Dark: "#333333"})

	BorderStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(ColorBorder).
			Padding(0, 1)

	CommandInputStyle = lipgloss.NewStyle().
				Foreground(ColorPrimary).
				Bold(true)
)

// StatusBadge returns a styled status indicator.
func StatusBadge(status string) string {
	switch status {
	case "Running", "Available", "True", "ready", "Ready":
		return SuccessStyle.Render("● " + status)
	case "Pending", "Progressing", "Unknown":
		return WarningStyle.Render("◐ " + status)
	case "Failed", "Error", "CrashLoopBackOff", "False", "Not Ready":
		return ErrorStyle.Render("✖ " + status)
	default:
		return MutedStyle.Render("○ " + status)
	}
}

// Pluralize returns a simple pluralized label.
func Pluralize(n int, singular, plural string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, singular)
	}
	return fmt.Sprintf("%d %s", n, plural)
}

// TruncateString truncates a string to maxLen with ellipsis.
func TruncateString(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	if maxLen < 4 {
		return s[:maxLen]
	}
	return s[:maxLen-3] + "..."
}
