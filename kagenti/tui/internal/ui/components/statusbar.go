package components

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"

	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// StatusBar renders the bottom status bar.
type StatusBar struct {
	Namespace string
	URL       string
	User      string
	Width     int
}

// NewStatusBar creates a new status bar.
func NewStatusBar(namespace, url, user string) StatusBar {
	return StatusBar{
		Namespace: namespace,
		URL:       url,
		User:      user,
	}
}

// View renders the status bar.
func (s StatusBar) View() string {
	ns := theme.LabelStyle.Render("ns:") + " " + s.Namespace
	url := theme.MutedStyle.Render(s.URL)

	user := s.User
	if user == "" {
		user = "guest"
	}
	userLabel := theme.LabelStyle.Render("user:") + " " + user

	hint := theme.MutedStyle.Render("/ command  •  ctrl+c quit")

	left := fmt.Sprintf(" %s  │  %s  │  %s", ns, url, userLabel)
	right := fmt.Sprintf("%s ", hint)

	gap := s.Width - lipgloss.Width(left) - lipgloss.Width(right)
	if gap < 0 {
		gap = 0
	}

	bar := left + lipgloss.NewStyle().Render(fmt.Sprintf("%*s", gap, "")) + right

	return theme.StatusBarStyle.Width(s.Width).Render(bar)
}
