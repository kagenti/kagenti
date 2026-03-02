package views

import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// ToolDetailView shows details for a single tool.
type ToolDetailView struct {
	client  *api.Client
	width   int
	height  int
	loading bool
	name    string
	detail  map[string]any
	err     error
	polling bool
}

// NewToolDetailView creates a new tool detail view.
func NewToolDetailView(client *api.Client) ToolDetailView {
	return ToolDetailView{client: client}
}

// SetSize sets the view dimensions.
func (v *ToolDetailView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

// SetTool sets the tool name to display.
func (v *ToolDetailView) SetTool(name string) {
	v.name = name
}

type toolDetailMsg struct {
	detail map[string]any
	err    error
}

type toolPollTickMsg struct{}

// Init fetches tool detail.
func (v ToolDetailView) Init() tea.Cmd {
	v.polling = true
	client := v.client
	name := v.name
	return func() tea.Msg {
		detail, err := client.GetTool("", name)
		if err != nil {
			return toolDetailMsg{err: err}
		}
		return toolDetailMsg{detail: detail}
	}
}

// Update handles messages.
func (v ToolDetailView) Update(msg tea.Msg) (ToolDetailView, tea.Cmd) {
	switch msg.(type) {
	case toolDetailMsg:
		m := msg.(toolDetailMsg)
		v.loading = false
		v.detail = m.detail
		v.err = m.err

		// Start polling if status is not terminal
		rs := v.readyStatus()
		if rs != "Ready" && rs != "Failed" && m.err == nil {
			v.polling = true
			return v, tea.Tick(3*time.Second, func(time.Time) tea.Msg {
				return toolPollTickMsg{}
			})
		}
		v.polling = false

	case toolPollTickMsg:
		// Re-fetch detail
		client := v.client
		name := v.name
		return v, func() tea.Msg {
			detail, err := client.GetTool("", name)
			if err != nil {
				return toolDetailMsg{err: err}
			}
			return toolDetailMsg{detail: detail}
		}
	}
	return v, nil
}

// readyStatus extracts the readyStatus string from the detail.
func (v ToolDetailView) readyStatus() string {
	if v.detail == nil {
		return ""
	}
	return str(v.detail["readyStatus"])
}

// View renders the tool detail.
func (v ToolDetailView) View() string {
	var b strings.Builder

	b.WriteString(theme.TitleStyle.Render("Tool: "+v.name) + "\n\n")

	if v.loading {
		b.WriteString(theme.MutedStyle.Render("  Loading..."))
		return b.String()
	}
	if v.err != nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Error: %s", v.err.Error())))
		return b.String()
	}
	if v.detail == nil {
		b.WriteString(theme.MutedStyle.Render("  No data"))
		return b.String()
	}

	if meta, ok := v.detail["metadata"].(map[string]any); ok {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Name:"), str(meta["name"])))
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Namespace:"), str(meta["namespace"])))
		if labels, ok := meta["labels"].(map[string]any); ok {
			if p := str(labels["kagenti.dev/protocol"]); p != "" {
				b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Protocol:"), p))
			}
			if f := str(labels["kagenti.dev/framework"]); f != "" {
				b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Framework:"), f))
			}
		}
		if annotations, ok := meta["annotations"].(map[string]any); ok {
			if desc := str(annotations["kagenti.dev/description"]); desc != "" {
				b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Description:"), desc))
			}
		}
	}

	if wt := str(v.detail["workloadType"]); wt != "" {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Workload:"), wt))
	}

	// Status
	if rs := v.readyStatus(); rs != "" {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Status:"), theme.StatusBadge(rs)))
	}

	// K8s status details (replicas and conditions)
	renderK8sStatus(&b, v.detail)

	// Service info
	if svc, ok := v.detail["service"].(map[string]any); ok {
		b.WriteString("\n" + theme.SubtitleStyle.Render("  Service") + "\n")
		b.WriteString(fmt.Sprintf("    %-14s %s\n", theme.LabelStyle.Render("Name:"), str(svc["name"])))
		b.WriteString(fmt.Sprintf("    %-14s %s\n", theme.LabelStyle.Render("ClusterIP:"), str(svc["clusterIP"])))
	}

	// MCP tools
	if mcpTools, ok := v.detail["mcpTools"].([]any); ok && len(mcpTools) > 0 {
		b.WriteString("\n" + theme.SubtitleStyle.Render("  MCP Tools") + "\n")
		for _, t := range mcpTools {
			if tm, ok := t.(map[string]any); ok {
				b.WriteString(fmt.Sprintf("    %s  %s\n",
					theme.LabelStyle.Render(str(tm["name"])),
					theme.MutedStyle.Render(str(tm["description"]))))
			}
		}
	}

	// Polling indicator
	hint := "Esc back"
	if v.polling {
		hint = "Auto-refreshing...  •  " + hint
	}
	b.WriteString("\n" + theme.MutedStyle.Render("  "+hint))

	return b.String()
}
