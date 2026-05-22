package views

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

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
	polling bool
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

type agentPollTickMsg struct{}

// Init fetches agent detail.
func (v AgentDetailView) Init() tea.Cmd {
	v.polling = true
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
	switch msg.(type) {
	case agentDetailMsg:
		m := msg.(agentDetailMsg)
		v.loading = false
		v.detail = m.detail
		v.err = m.err

		// Start polling if status is not terminal
		rs := v.readyStatus()
		if rs != "Ready" && rs != "Failed" && m.err == nil {
			v.polling = true
			return v, tea.Tick(3*time.Second, func(time.Time) tea.Msg {
				return agentPollTickMsg{}
			})
		}
		v.polling = false

	case agentPollTickMsg:
		// Re-fetch detail
		client := v.client
		name := v.name
		return v, func() tea.Msg {
			detail, err := client.GetAgent("", name)
			if err != nil {
				return agentDetailMsg{err: err}
			}
			return agentDetailMsg{detail: detail}
		}
	}
	return v, nil
}

// readyStatus extracts the readyStatus string from the detail.
func (v AgentDetailView) readyStatus() string {
	if v.detail == nil {
		return ""
	}
	return str(v.detail["readyStatus"])
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
	if rs := v.readyStatus(); rs != "" {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Status:"), theme.StatusBadge(rs)))
	}

	// K8s status details (replicas and conditions)
	renderK8sStatus(&b, v.detail)

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

	// Environment variables
	renderEnvVars(&b, v.detail)

	// Polling indicator
	hint := "Esc back  •  /chat " + v.name + " to chat"
	if v.polling {
		hint = "Auto-refreshing...  •  " + hint
	}
	b.WriteString("\n" + theme.MutedStyle.Render("  "+hint))

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

// isSensitiveKey returns true if the env var name likely contains a secret.
func isSensitiveKey(name string) bool {
	upper := strings.ToUpper(name)
	for _, tok := range []string{"KEY", "SECRET", "TOKEN", "PASSWORD"} {
		if strings.Contains(upper, tok) {
			return true
		}
	}
	return false
}

// renderEnvVars writes the environment variables section from
// spec.template.spec.containers[0].env[].
func renderEnvVars(b *strings.Builder, detail map[string]any) {
	spec, ok := detail["spec"].(map[string]any)
	if !ok {
		return
	}
	tmpl, ok := spec["template"].(map[string]any)
	if !ok {
		return
	}
	podSpec, ok := tmpl["spec"].(map[string]any)
	if !ok {
		return
	}
	containers, ok := podSpec["containers"].([]any)
	if !ok || len(containers) == 0 {
		return
	}
	cm, ok := containers[0].(map[string]any)
	if !ok {
		return
	}
	envList, ok := cm["env"].([]any)
	if !ok || len(envList) == 0 {
		return
	}

	b.WriteString("\n" + theme.SubtitleStyle.Render("  Environment") + "\n")
	for _, e := range envList {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		name := str(entry["name"])
		if name == "" {
			continue
		}

		var display string
		if vf, ok := entry["valueFrom"].(map[string]any); ok {
			if ref, ok := vf["secretKeyRef"].(map[string]any); ok {
				display = fmt.Sprintf("<secret:%s/%s>", str(ref["name"]), str(ref["key"]))
			} else {
				display = "<ref>"
			}
		} else if isSensitiveKey(name) {
			display = "***"
		} else {
			display = str(entry["value"])
		}
		b.WriteString(fmt.Sprintf("    %-16s %s\n",
			theme.LabelStyle.Render(name+":"),
			theme.MutedStyle.Render(display)))
	}
}

// renderK8sStatus writes replica counts and conditions from the status field.
func renderK8sStatus(b *strings.Builder, detail map[string]any) {
	status, ok := detail["status"].(map[string]any)
	if !ok {
		return
	}

	// Replica counts
	replicas := str(status["replicas"])
	readyReplicas := str(status["readyReplicas"])
	availableReplicas := str(status["availableReplicas"])
	if replicas != "" || readyReplicas != "" {
		b.WriteString("\n" + theme.SubtitleStyle.Render("  Replicas") + "\n")
		if replicas != "" {
			b.WriteString(fmt.Sprintf("    %-16s %s\n", theme.LabelStyle.Render("Desired:"), replicas))
		}
		if readyReplicas != "" {
			b.WriteString(fmt.Sprintf("    %-16s %s\n", theme.LabelStyle.Render("Ready:"), readyReplicas))
		}
		if availableReplicas != "" {
			b.WriteString(fmt.Sprintf("    %-16s %s\n", theme.LabelStyle.Render("Available:"), availableReplicas))
		}
	}

	// Conditions
	conditions, ok := status["conditions"].([]any)
	if !ok || len(conditions) == 0 {
		return
	}
	b.WriteString("\n" + theme.SubtitleStyle.Render("  Conditions") + "\n")
	for _, c := range conditions {
		cond, ok := c.(map[string]any)
		if !ok {
			continue
		}
		condType := str(cond["type"])
		condStatus := str(cond["status"])
		reason := str(cond["reason"])
		message := str(cond["message"])

		badge := theme.StatusBadge(condStatus)
		line := fmt.Sprintf("    %s %s", badge, theme.LabelStyle.Render(condType))
		if reason != "" {
			line += fmt.Sprintf("  %s", theme.MutedStyle.Render(reason))
		}
		b.WriteString(line + "\n")
		if message != "" {
			b.WriteString(fmt.Sprintf("      %s\n", theme.MutedStyle.Render(message)))
		}
	}
}
