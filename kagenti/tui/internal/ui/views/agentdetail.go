package views

import (
	"encoding/json"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// AgentDetailView shows details for a single agent.
type AgentDetailView struct {
	client  *api.Client
	width   int
	height  int
	loading bool
	name    string
	detail  map[string]any
	err     error
}

// NewAgentDetailView creates a new agent detail view.
func NewAgentDetailView(client *api.Client) AgentDetailView {
	return AgentDetailView{client: client}
}

// SetSize sets the view dimensions.
func (v *AgentDetailView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

// SetAgent sets the agent name to display.
func (v *AgentDetailView) SetAgent(name string) {
	v.name = name
}

type agentDetailMsg struct {
	detail map[string]any
	err    error
}

// Init fetches agent detail.
func (v AgentDetailView) Init() tea.Cmd {
	client := v.client
	name := v.name
	return func() tea.Msg {
		detail, err := client.GetAgent("", name)
		if err != nil {
			return agentDetailMsg{err: err}
		}
		return agentDetailMsg{detail: detail}
	}
}

// Update handles messages.
func (v AgentDetailView) Update(msg tea.Msg) (AgentDetailView, tea.Cmd) {
	switch msg := msg.(type) {
	case agentDetailMsg:
		v.loading = false
		v.detail = msg.detail
		v.err = msg.err
	}
	return v, nil
}

// View renders the agent detail.
func (v AgentDetailView) View() string {
	var b strings.Builder

	b.WriteString(theme.TitleStyle.Render("Agent: "+v.name) + "\n\n")

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

	// Extract metadata
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

	// Workload type
	if wt := str(v.detail["workloadType"]); wt != "" {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Workload:"), wt))
	}

	// Status
	if rs, ok := v.detail["readyStatus"].(map[string]any); ok {
		ready := str(rs["ready"])
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Ready:"), theme.StatusBadge(ready)))
		if msg := str(rs["message"]); msg != "" {
			b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Message:"), theme.MutedStyle.Render(msg)))
		}
	}

	// Containers
	if spec, ok := v.detail["spec"].(map[string]any); ok {
		if tmpl, ok := spec["template"].(map[string]any); ok {
			if podSpec, ok := tmpl["spec"].(map[string]any); ok {
				if containers, ok := podSpec["containers"].([]any); ok && len(containers) > 0 {
					b.WriteString("\n" + theme.SubtitleStyle.Render("  Containers") + "\n")
					for _, c := range containers {
						if cm, ok := c.(map[string]any); ok {
							b.WriteString(fmt.Sprintf("    %-16s %s\n",
								theme.LabelStyle.Render(str(cm["name"])+":"),
								theme.MutedStyle.Render(str(cm["image"]))))
						}
					}
				}
			}
		}
	}

	// Raw JSON fallback for other fields
	b.WriteString("\n" + theme.MutedStyle.Render("  Esc back  •  /chat "+v.name+" to chat"))

	return b.String()
}

func str(v any) string {
	if v == nil {
		return ""
	}
	switch val := v.(type) {
	case string:
		return val
	case json.Number:
		return val.String()
	case float64:
		return fmt.Sprintf("%v", val)
	case bool:
		return fmt.Sprintf("%v", val)
	default:
		return fmt.Sprintf("%v", val)
	}
}
