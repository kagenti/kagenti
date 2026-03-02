package ui

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/command"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui/components"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui/views"
)

// ViewID identifies the active view.
type ViewID int

const (
	ViewHome ViewID = iota
	ViewAgents
	ViewAgentDetail
	ViewTools
	ViewToolDetail
	ViewChat
	ViewDeployAgent
	ViewDeployTool
	ViewLogin
	ViewHelp
)

// App is the root Bubble Tea model.
type App struct {
	client   *api.Client
	registry *command.Registry
	cmdInput components.CommandInput
	bar      components.StatusBar

	view   ViewID
	width  int
	height int
	user   string
	authOn bool
	err    error

	// Sub-views
	homeView        views.HomeView
	agentsView      views.AgentsView
	agentDetailView views.AgentDetailView
	toolsView       views.ToolsView
	toolDetailView  views.ToolDetailView
	chatView        views.ChatView
	deployAgentView views.DeployAgentView
	deployToolView  views.DeployToolView
	loginView       views.LoginView
}

// NewApp creates the root app model.
func NewApp(client *api.Client) App {
	registry := command.NewRegistry()
	return App{
		client:   client,
		registry: registry,
		cmdInput: components.NewCommandInput(registry),
		bar:      components.NewStatusBar(client.Namespace, client.BaseURL, ""),
		view:     ViewHome,

		homeView:        views.NewHomeView(client),
		agentsView:      views.NewAgentsView(client),
		agentDetailView: views.NewAgentDetailView(client),
		toolsView:       views.NewToolsView(client),
		toolDetailView:  views.NewToolDetailView(client),
		chatView:        views.NewChatView(client),
		deployAgentView: views.NewDeployAgentView(client),
		deployToolView:  views.NewDeployToolView(client),
		loginView:       views.NewLoginView(client),
	}
}

// Init starts the app by fetching initial status.
func (a App) Init() tea.Cmd {
	return tea.Batch(
		a.homeView.Init(),
		a.fetchUser(),
	)
}

// fetchUser loads the current user info.
func (a App) fetchUser() tea.Cmd {
	return func() tea.Msg {
		user, err := a.client.GetCurrentUser()
		if err != nil {
			return userFetchedMsg{err: err}
		}
		return userFetchedMsg{user: user}
	}
}

type userFetchedMsg struct {
	user *api.UserInfoResponse
	err  error
}

// Update handles messages.
func (a App) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		a.width = msg.Width
		a.height = msg.Height
		a.bar.Width = msg.Width
		a.homeView.SetSize(msg.Width, msg.Height-2)
		a.agentsView.SetSize(msg.Width, msg.Height-2)
		a.agentDetailView.SetSize(msg.Width, msg.Height-2)
		a.toolsView.SetSize(msg.Width, msg.Height-2)
		a.toolDetailView.SetSize(msg.Width, msg.Height-2)
		a.chatView.SetSize(msg.Width, msg.Height-2)
		a.deployAgentView.SetSize(msg.Width, msg.Height-2)
		a.deployToolView.SetSize(msg.Width, msg.Height-2)
		a.loginView.SetSize(msg.Width, msg.Height-2)
		return a, nil

	case userFetchedMsg:
		if msg.err == nil && msg.user != nil {
			a.user = msg.user.Username
			a.bar.User = a.user
			a.authOn = msg.user.Authenticated
		}
		return a, nil

	case tea.KeyMsg:
		// Global ctrl+c always quits
		if msg.Type == tea.KeyCtrlC {
			return a, tea.Quit
		}

		// If command input is active, delegate to it
		if a.cmdInput.Active() {
			cmd := a.cmdInput.Update(msg)
			return a, cmd
		}

		// "/" activates command input (unless in chat/form mode)
		if msg.String() == "/" && a.view != ViewChat && a.view != ViewDeployAgent && a.view != ViewDeployTool {
			a.cmdInput.Activate()
			return a, nil
		}

		// Esc returns to home from any view
		if msg.Type == tea.KeyEsc {
			if a.view != ViewHome {
				a.view = ViewHome
				return a, a.homeView.Init()
			}
		}

	case components.CommandSubmittedMsg:
		return a.handleCommand(msg.Command, msg.Args)

	case views.NavigateMsg:
		return a.handleNavigate(msg)
	}

	// Delegate to active sub-view
	var cmd tea.Cmd
	switch a.view {
	case ViewHome:
		a.homeView, cmd = a.homeView.Update(msg)
	case ViewAgents:
		a.agentsView, cmd = a.agentsView.Update(msg)
	case ViewAgentDetail:
		a.agentDetailView, cmd = a.agentDetailView.Update(msg)
	case ViewTools:
		a.toolsView, cmd = a.toolsView.Update(msg)
	case ViewToolDetail:
		a.toolDetailView, cmd = a.toolDetailView.Update(msg)
	case ViewChat:
		a.chatView, cmd = a.chatView.Update(msg)
	case ViewDeployAgent:
		a.deployAgentView, cmd = a.deployAgentView.Update(msg)
	case ViewDeployTool:
		a.deployToolView, cmd = a.deployToolView.Update(msg)
	case ViewLogin:
		a.loginView, cmd = a.loginView.Update(msg)
	}
	cmds = append(cmds, cmd)

	return a, tea.Batch(cmds...)
}

// handleCommand dispatches a parsed command.
func (a App) handleCommand(cmd, args string) (tea.Model, tea.Cmd) {
	switch cmd {
	case "agents":
		a.view = ViewAgents
		return a, a.agentsView.Init()

	case "agent":
		if args == "" {
			a.err = fmt.Errorf("usage: /agent <name>")
			return a, nil
		}
		a.agentDetailView.SetAgent(args)
		a.view = ViewAgentDetail
		return a, a.agentDetailView.Init()

	case "tools":
		a.view = ViewTools
		return a, a.toolsView.Init()

	case "tool":
		if args == "" {
			a.err = fmt.Errorf("usage: /tool <name>")
			return a, nil
		}
		a.toolDetailView.SetTool(args)
		a.view = ViewToolDetail
		return a, a.toolDetailView.Init()

	case "chat":
		if args == "" {
			a.err = fmt.Errorf("usage: /chat <agent>")
			return a, nil
		}
		a.chatView.SetAgent(args)
		a.view = ViewChat
		return a, a.chatView.Init()

	case "deploy":
		switch args {
		case "agent":
			a.deployAgentView = views.NewDeployAgentView(a.client)
			a.deployAgentView.SetSize(a.width, a.height-2)
			a.view = ViewDeployAgent
			return a, a.deployAgentView.Init()
		case "tool":
			a.deployToolView = views.NewDeployToolView(a.client)
			a.deployToolView.SetSize(a.width, a.height-2)
			a.view = ViewDeployTool
			return a, a.deployToolView.Init()
		default:
			a.err = fmt.Errorf("usage: /deploy agent|tool")
			return a, nil
		}

	case "delete":
		parts := strings.SplitN(args, " ", 2)
		if len(parts) < 2 {
			a.err = fmt.Errorf("usage: /delete agent|tool <name>")
			return a, nil
		}
		return a, a.doDelete(parts[0], parts[1])

	case "ns":
		if args != "" {
			a.client.SetNamespace(args)
			a.bar.Namespace = args
			a.view = ViewHome
			return a, a.homeView.Init()
		}
		a.err = fmt.Errorf("usage: /ns <name>")
		return a, nil

	case "login":
		a.view = ViewLogin
		return a, a.loginView.Init()

	case "logout":
		a.client.SetToken("")
		a.user = "guest"
		a.bar.User = "guest"
		a.view = ViewHome
		return a, a.homeView.Init()

	case "status":
		a.view = ViewHome
		return a, a.homeView.Init()

	case "help":
		a.view = ViewHelp
		return a, nil

	case "quit":
		return a, tea.Quit

	default:
		a.err = fmt.Errorf("unknown command: /%s", cmd)
		return a, nil
	}
}

// handleNavigate handles navigation messages from sub-views.
func (a App) handleNavigate(msg views.NavigateMsg) (tea.Model, tea.Cmd) {
	switch msg.Target {
	case "home":
		a.view = ViewHome
		return a, tea.Batch(a.homeView.Init(), a.fetchUser())
	case "agent-detail":
		a.agentDetailView.SetAgent(msg.Name)
		a.view = ViewAgentDetail
		return a, a.agentDetailView.Init()
	case "tool-detail":
		a.toolDetailView.SetTool(msg.Name)
		a.view = ViewToolDetail
		return a, a.toolDetailView.Init()
	}
	return a, nil
}

type deleteResultMsg struct {
	success bool
	message string
	err     error
}

// doDelete performs a delete operation.
func (a App) doDelete(kind, name string) tea.Cmd {
	return func() tea.Msg {
		var err error
		var resp *api.DeleteResponse

		switch kind {
		case "agent":
			resp, err = a.client.DeleteAgent("", name)
		case "tool":
			resp, err = a.client.DeleteTool("", name)
		default:
			return deleteResultMsg{err: fmt.Errorf("unknown resource type: %s", kind)}
		}
		if err != nil {
			return deleteResultMsg{err: err}
		}
		return deleteResultMsg{success: resp.Success, message: resp.Message}
	}
}

// View renders the app.
func (a App) View() string {
	var content string

	switch a.view {
	case ViewHome:
		content = a.homeView.View()
	case ViewAgents:
		content = a.agentsView.View()
	case ViewAgentDetail:
		content = a.agentDetailView.View()
	case ViewTools:
		content = a.toolsView.View()
	case ViewToolDetail:
		content = a.toolDetailView.View()
	case ViewChat:
		content = a.chatView.View()
	case ViewDeployAgent:
		content = a.deployAgentView.View()
	case ViewDeployTool:
		content = a.deployToolView.View()
	case ViewLogin:
		content = a.loginView.View()
	case ViewHelp:
		content = a.helpView()
	}

	if a.err != nil {
		content += "\n" + theme.ErrorStyle.Render(a.err.Error())
		a.err = nil
	}

	// Command input overlay
	if a.cmdInput.Active() {
		content += "\n\n" + a.cmdInput.View()
	}

	// Status bar at bottom
	bar := a.bar.View()

	// Fill to height
	contentHeight := a.height - 1
	lines := strings.Split(content, "\n")
	if len(lines) < contentHeight {
		content += strings.Repeat("\n", contentHeight-len(lines))
	}

	return content + "\n" + bar
}

// helpView renders the help screen.
func (a App) helpView() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Kagenti TUI — Commands") + "\n\n")

	for _, cmd := range a.registry.All() {
		name := "/" + cmd.Name
		if cmd.HasArg {
			name += " " + cmd.ArgHint
		}
		b.WriteString(fmt.Sprintf("  %-30s %s\n", theme.LabelStyle.Render(name), cmd.Description))
	}

	b.WriteString("\n" + theme.MutedStyle.Render("  Press Esc to return home"))
	return b.String()
}
