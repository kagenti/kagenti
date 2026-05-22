package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// ToolsView shows a table of tools.
type ToolsView struct {
	client   *api.Client
	width    int
	height   int
	loading  bool
	tools    []api.ToolSummary
	selected int
	err      error
}

// NewToolsView creates a new tools list view.
func NewToolsView(client *api.Client) ToolsView {
	return ToolsView{client: client}
}

// SetSize sets the view dimensions.
func (v *ToolsView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type toolsLoadedMsg struct {
	tools []api.ToolSummary
	err   error
}

// Init fetches tool list.
func (v ToolsView) Init() tea.Cmd {
	client := v.client
	return func() tea.Msg {
		resp, err := client.ListTools("")
		if err != nil {
			return toolsLoadedMsg{err: err}
		}
		return toolsLoadedMsg{tools: resp.Items}
	}
}

// Update handles messages.
func (v ToolsView) Update(msg tea.Msg) (ToolsView, tea.Cmd) {
	switch msg := msg.(type) {
	case toolsLoadedMsg:
		v.loading = false
		v.tools = msg.tools
		v.err = msg.err
		v.selected = 0

	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyUp:
			if v.selected > 0 {
				v.selected--
			}
		case tea.KeyDown:
			if v.selected < len(v.tools)-1 {
				v.selected++
			}
		case tea.KeyEnter:
			if len(v.tools) > 0 && v.selected < len(v.tools) {
				tool := v.tools[v.selected]
				return v, func() tea.Msg {
					return NavigateMsg{Target: "tool-detail", Name: tool.Name}
				}
			}
		}
	}
	return v, nil
}

// View renders the tool table.
func (v ToolsView) View() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Tools") +
		theme.MutedStyle.Render(fmt.Sprintf(" (%s)", v.client.Namespace)) + "\n\n")

	if v.loading {
		b.WriteString(theme.MutedStyle.Render("  Loading..."))
		return b.String()
	}
	if v.err != nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Error: %s", v.err.Error())))
		return b.String()
	}
	if len(v.tools) == 0 {
		b.WriteString(theme.MutedStyle.Render("  No tools found"))
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

	for i, t := range v.tools {
		cursor := "  "
		if i == v.selected {
			cursor = "▸ "
		}

		name := theme.TruncateString(t.Name, 22)
		status := theme.StatusBadge(t.Status)
		desc := theme.TruncateString(t.Description, 40)

		line := fmt.Sprintf("%s%-24s %-14s %-12s %-12s %s",
			cursor, name, status, t.Labels.Protocol, t.Labels.Framework, theme.MutedStyle.Render(desc))

		if i == v.selected {
			line = theme.CommandInputStyle.Render(line)
		}
		b.WriteString(line + "\n")
	}

	b.WriteString("\n" + theme.MutedStyle.Render("  ↑/↓ navigate  •  Enter details  •  Esc back"))
	return b.String()
}
