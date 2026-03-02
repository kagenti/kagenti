package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// AgentsView shows a table of agents.
type AgentsView struct {
	client   *api.Client
	width    int
	height   int
	loading  bool
	agents   []api.AgentSummary
	selected int
	err      error
}

// NewAgentsView creates a new agents list view.
func NewAgentsView(client *api.Client) AgentsView {
	return AgentsView{client: client}
}

// SetSize sets the view dimensions.
func (v *AgentsView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type agentsLoadedMsg struct {
	agents []api.AgentSummary
	err    error
}

// Init fetches agent list.
func (v AgentsView) Init() tea.Cmd {
	v.loading = true
	client := v.client
	return func() tea.Msg {
		resp, err := client.ListAgents("")
		if err != nil {
			return agentsLoadedMsg{err: err}
		}
		return agentsLoadedMsg{agents: resp.Items}
	}
}

// Update handles messages.
func (v AgentsView) Update(msg tea.Msg) (AgentsView, tea.Cmd) {
	switch msg := msg.(type) {
	case agentsLoadedMsg:
		v.loading = false
		v.agents = msg.agents
		v.err = msg.err
		v.selected = 0

	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyUp:
			if v.selected > 0 {
				v.selected--
			}
		case tea.KeyDown:
			if v.selected < len(v.agents)-1 {
				v.selected++
			}
		case tea.KeyEnter:
			if len(v.agents) > 0 && v.selected < len(v.agents) {
				agent := v.agents[v.selected]
				return v, func() tea.Msg {
					return NavigateMsg{Target: "agent-detail", Name: agent.Name}
				}
			}
		}
	}
	return v, nil
}

// View renders the agent table.
func (v AgentsView) View() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Agents") +
		theme.MutedStyle.Render(fmt.Sprintf(" (%s)", v.client.Namespace)) + "\n\n")

	if v.loading {
		b.WriteString(theme.MutedStyle.Render("  Loading..."))
		return b.String()
	}
	if v.err != nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Error: %s", v.err.Error())))
		return b.String()
	}
	if len(v.agents) == 0 {
		b.WriteString(theme.MutedStyle.Render("  No agents found"))
		return b.String()
	}

	header := fmt.Sprintf("  %-24s %-14s %-12s %-12s %s",
		theme.LabelStyle.Render("NAME"),
		theme.LabelStyle.Render("STATUS"),
		theme.LabelStyle.Render("PROTOCOL"),
		theme.LabelStyle.Render("FRAMEWORK"),
		theme.LabelStyle.Render("DESCRIPTION"),
	)
	b.WriteString(header + "\n")

	for i, a := range v.agents {
		cursor := "  "
		if i == v.selected {
			cursor = "▸ "
		}

		name := theme.TruncateString(a.Name, 22)
		status := theme.StatusBadge(a.Status)
		desc := theme.TruncateString(a.Description, 40)

		line := fmt.Sprintf("%s%-24s %-14s %-12s %-12s %s",
			cursor, name, status, a.Labels.Protocol, a.Labels.Framework, theme.MutedStyle.Render(desc))

		if i == v.selected {
			line = theme.CommandInputStyle.Render(line)
		}
		b.WriteString(line + "\n")
	}

	b.WriteString("\n" + theme.MutedStyle.Render("  ↑/↓ navigate  •  Enter details  •  Esc back"))
	return b.String()
}
