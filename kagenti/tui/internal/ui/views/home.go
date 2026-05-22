package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
	"github.com/kagenti/kagenti/kagenti/tui/internal/version"
)

// HomeView is the status dashboard shown on launch.
type HomeView struct {
	client      *api.Client
	width       int
	height      int
	loading     bool
	connOK      bool
	authEnabled bool
	authOK      bool
	userName    string
	agentCount  int
	toolCount   int
	namespace   string
	dashURLs    *api.DashboardConfigResponse
	err         error
}

// NewHomeView creates a new home view.
func NewHomeView(client *api.Client) HomeView {
	return HomeView{client: client, loading: true}
}

// SetSize sets the view dimensions.
func (v *HomeView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type homeDataMsg struct {
	connOK      bool
	authEnabled bool
	authOK      bool
	userName    string
	agentCount  int
	toolCount   int
	namespace   string
	dashURLs    *api.DashboardConfigResponse
	err         error
}

// Init fetches all dashboard data.
func (v HomeView) Init() tea.Cmd {
	client := v.client
	return func() tea.Msg {
		result := homeDataMsg{namespace: client.Namespace}

		authStatus, err := client.GetAuthStatus()
		if err != nil {
			result.err = err
			return result
		}
		result.connOK = true
		result.authEnabled = authStatus.Enabled
		result.authOK = authStatus.Authenticated

		if user, err := client.GetCurrentUser(); err == nil {
			result.userName = user.Username
		}

		if agents, err := client.ListAgents(""); err == nil {
			result.agentCount = len(agents.Items)
		}

		if tools, err := client.ListTools(""); err == nil {
			result.toolCount = len(tools.Items)
		}

		if dash, err := client.GetDashboardConfig(); err == nil {
			result.dashURLs = dash
		}

		return result
	}
}

// Update handles messages.
func (v HomeView) Update(msg tea.Msg) (HomeView, tea.Cmd) {
	switch msg := msg.(type) {
	case homeDataMsg:
		v.loading = false
		v.connOK = msg.connOK
		v.authEnabled = msg.authEnabled
		v.authOK = msg.authOK
		v.userName = msg.userName
		v.agentCount = msg.agentCount
		v.toolCount = msg.toolCount
		v.namespace = msg.namespace
		v.dashURLs = msg.dashURLs
		v.err = msg.err
	}
	return v, nil
}

// View renders the home dashboard.
func (v HomeView) View() string {
	var b strings.Builder

	b.WriteString(theme.TitleStyle.Render("Kagenti") + theme.MutedStyle.Render(" "+version.Version) + "\n\n")

	if v.loading {
		b.WriteString(theme.MutedStyle.Render("  Loading..."))
		return b.String()
	}

	if v.err != nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Connection failed: %s", v.err.Error())) + "\n")
		b.WriteString(theme.MutedStyle.Render(fmt.Sprintf("  URL: %s", v.client.BaseURL)) + "\n")
		return b.String()
	}

	connStatus := theme.SuccessStyle.Render("● Connected")
	b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Connection:"), connStatus))
	b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("URL:"), theme.ValueStyle.Render(v.client.BaseURL)))
	b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Namespace:"), theme.ValueStyle.Render(v.namespace)))

	if v.authEnabled {
		authStatus := theme.ErrorStyle.Render("● Not authenticated")
		if v.authOK {
			authStatus = theme.SuccessStyle.Render("● Authenticated")
		}
		b.WriteString(fmt.Sprintf("  %-18s %s", theme.LabelStyle.Render("Auth:"), authStatus))
		if v.userName != "" && v.userName != "guest" {
			b.WriteString(fmt.Sprintf(" (%s)", v.userName))
		}
		b.WriteString("\n")
	} else {
		b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Auth:"), theme.MutedStyle.Render("disabled")))
	}

	b.WriteString("\n")
	b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Agents:"), theme.ValueStyle.Render(fmt.Sprintf("%d", v.agentCount))))
	b.WriteString(fmt.Sprintf("  %-18s %s\n", theme.LabelStyle.Render("Tools:"), theme.ValueStyle.Render(fmt.Sprintf("%d", v.toolCount))))

	if v.dashURLs != nil {
		b.WriteString("\n")
		b.WriteString(theme.SubtitleStyle.Render("  Dashboard Links") + "\n")
		if v.dashURLs.Traces != "" {
			b.WriteString(fmt.Sprintf("    Traces:       %s\n", theme.MutedStyle.Render(v.dashURLs.Traces)))
		}
		if v.dashURLs.Network != "" {
			b.WriteString(fmt.Sprintf("    Network:      %s\n", theme.MutedStyle.Render(v.dashURLs.Network)))
		}
		if v.dashURLs.KeycloakConsole != "" {
			b.WriteString(fmt.Sprintf("    Keycloak:     %s\n", theme.MutedStyle.Render(v.dashURLs.KeycloakConsole)))
		}
	}

	b.WriteString("\n" + theme.MutedStyle.Render("  Type / to enter a command, /help for all commands"))

	return b.String()
}
