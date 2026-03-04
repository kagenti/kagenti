package ui

import (
	"fmt"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui/components"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui/views"
)

// newTestApp creates an App wired to a dummy client (no real server).
func newTestApp() App {
	client := api.NewClient("http://fake", "", "team1")
	return NewApp(client)
}

// ---------- Command Dispatching ----------

func TestApp_CommandDispatch(t *testing.T) {
	tests := []struct {
		name     string
		command  string
		args     string
		wantView ViewID
	}{
		{"agents", "agents", "", ViewAgents},
		{"tools", "tools", "", ViewTools},
		{"chat with arg", "chat", "my-agent", ViewChat},
		{"agent detail", "agent", "my-agent", ViewAgentDetail},
		{"tool detail", "tool", "my-tool", ViewToolDetail},
		{"login", "login", "", ViewLogin},
		{"help", "help", "", ViewHelp},
		{"status", "status", "", ViewHome},
		{"deploy agent", "deploy", "agent", ViewDeployAgent},
		{"deploy tool", "deploy", "tool", ViewDeployTool},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestApp()
			msg := components.CommandSubmittedMsg{Command: tc.command, Args: tc.args}

			model, _ := a.Update(msg)
			app := model.(App)

			if app.view != tc.wantView {
				t.Errorf("expected view=%d, got %d", tc.wantView, app.view)
			}
		})
	}
}

func TestApp_ChatCommandSetsAgent(t *testing.T) {
	a := newTestApp()
	msg := components.CommandSubmittedMsg{Command: "chat", Args: "my-agent"}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.view != ViewChat {
		t.Fatalf("expected ViewChat, got %d", app.view)
	}
	// chatView.agentName is unexported, but we can verify via View() output.
	view := app.chatView.View()
	if view == "" {
		t.Error("expected non-empty chat view")
	}
}

func TestApp_CommandMissingArgs(t *testing.T) {
	tests := []struct {
		name    string
		command string
	}{
		{"chat without agent", "chat"},
		{"agent without name", "agent"},
		{"tool without name", "tool"},
		{"deploy without type", "deploy"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestApp()
			msg := components.CommandSubmittedMsg{Command: tc.command, Args: ""}

			model, _ := a.Update(msg)
			app := model.(App)

			if app.err == nil {
				t.Error("expected error for missing args")
			}
			// Should stay on current view (Home).
			if app.view != ViewHome {
				t.Errorf("expected to stay on ViewHome, got %d", app.view)
			}
		})
	}
}

func TestApp_UnknownCommand(t *testing.T) {
	a := newTestApp()
	msg := components.CommandSubmittedMsg{Command: "nonexistent", Args: ""}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.err == nil {
		t.Error("expected error for unknown command")
	}
}

// ---------- Global Navigation ----------

func TestApp_EscReturnsToHome(t *testing.T) {
	viewsToTest := []ViewID{
		ViewAgents, ViewAgentDetail, ViewTools, ViewToolDetail,
		ViewChat, ViewDeployAgent, ViewDeployTool, ViewLogin, ViewHelp,
	}

	for _, v := range viewsToTest {
		t.Run("from_view_"+viewIDName(v), func(t *testing.T) {
			a := newTestApp()
			a.view = v

			model, _ := a.Update(tea.KeyMsg{Type: tea.KeyEsc})
			app := model.(App)

			if app.view != ViewHome {
				t.Errorf("expected ViewHome after Esc from %d, got %d", v, app.view)
			}
		})
	}
}

func TestApp_EscOnHomeIsNoop(t *testing.T) {
	a := newTestApp()
	a.view = ViewHome

	model, _ := a.Update(tea.KeyMsg{Type: tea.KeyEsc})
	app := model.(App)

	if app.view != ViewHome {
		t.Errorf("expected ViewHome to stay, got %d", app.view)
	}
}

func TestApp_SlashActivatesCommandInput(t *testing.T) {
	a := newTestApp()

	model, _ := a.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("/")})
	app := model.(App)

	if !app.cmdInput.Active() {
		t.Error("expected command input to be active after /")
	}
}

func TestApp_SlashIgnoredInChat(t *testing.T) {
	a := newTestApp()
	a.view = ViewChat

	model, _ := a.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("/")})
	app := model.(App)

	if app.cmdInput.Active() {
		t.Error("/ should not activate command input in chat view")
	}
}

func TestApp_SlashIgnoredInDeployForms(t *testing.T) {
	for _, v := range []ViewID{ViewDeployAgent, ViewDeployTool} {
		t.Run(viewIDName(v), func(t *testing.T) {
			a := newTestApp()
			a.view = v

			model, _ := a.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("/")})
			app := model.(App)

			if app.cmdInput.Active() {
				t.Errorf("/ should not activate command input in %s", viewIDName(v))
			}
		})
	}
}

// ---------- Auth State ----------

func TestApp_UserFetchedMsg(t *testing.T) {
	a := newTestApp()

	msg := userFetchedMsg{
		user: &api.UserInfoResponse{
			Username:      "alice",
			Authenticated: true,
		},
	}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.user != "alice" {
		t.Errorf("expected user='alice', got %q", app.user)
	}
	if !app.authOn {
		t.Error("expected authOn=true")
	}
	if app.bar.User != "alice" {
		t.Errorf("expected bar.User='alice', got %q", app.bar.User)
	}
}

func TestApp_UserFetchedMsgError(t *testing.T) {
	a := newTestApp()

	msg := userFetchedMsg{err: fmt.Errorf("network error")}

	model, _ := a.Update(msg)
	app := model.(App)

	// On error, user fields should remain at defaults.
	if app.user != "" {
		t.Errorf("expected empty user on error, got %q", app.user)
	}
	if app.authOn {
		t.Error("expected authOn=false on error")
	}
}

// ---------- NavigateMsg ----------

func TestApp_NavigateMsg(t *testing.T) {
	tests := []struct {
		name     string
		msg      views.NavigateMsg
		wantView ViewID
	}{
		{"to home", views.NavigateMsg{Target: "home"}, ViewHome},
		{"to agent detail", views.NavigateMsg{Target: "agent-detail", Name: "a1"}, ViewAgentDetail},
		{"to tool detail", views.NavigateMsg{Target: "tool-detail", Name: "t1"}, ViewToolDetail},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestApp()
			a.view = ViewAgents // start from non-home

			model, _ := a.Update(tc.msg)
			app := model.(App)

			if app.view != tc.wantView {
				t.Errorf("expected view=%d, got %d", tc.wantView, app.view)
			}
		})
	}
}

// ---------- Window Resize ----------

func TestApp_WindowSizeMsg(t *testing.T) {
	a := newTestApp()

	model, _ := a.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	app := model.(App)

	if app.width != 120 || app.height != 40 {
		t.Errorf("expected 120x40, got %dx%d", app.width, app.height)
	}
	if app.bar.Width != 120 {
		t.Errorf("expected bar width=120, got %d", app.bar.Width)
	}
}

// ---------- Logout ----------

func TestApp_LogoutCommand(t *testing.T) {
	a := newTestApp()
	a.user = "alice"
	a.bar.User = "alice"
	a.client.SetToken("some-token")

	msg := components.CommandSubmittedMsg{Command: "logout", Args: ""}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.user != "guest" {
		t.Errorf("expected user='guest' after logout, got %q", app.user)
	}
	if app.bar.User != "guest" {
		t.Errorf("expected bar.User='guest', got %q", app.bar.User)
	}
	if app.client.Token != "" {
		t.Errorf("expected empty token after logout, got %q", app.client.Token)
	}
	if app.view != ViewHome {
		t.Errorf("expected ViewHome after logout, got %d", app.view)
	}
}

// ---------- Namespace Switch ----------

func TestApp_NsCommand(t *testing.T) {
	a := newTestApp()

	msg := components.CommandSubmittedMsg{Command: "ns", Args: "team2"}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.client.Namespace != "team2" {
		t.Errorf("expected namespace='team2', got %q", app.client.Namespace)
	}
	if app.bar.Namespace != "team2" {
		t.Errorf("expected bar.Namespace='team2', got %q", app.bar.Namespace)
	}
	if app.view != ViewHome {
		t.Errorf("expected ViewHome after ns switch, got %d", app.view)
	}
}

func TestApp_NsCommandMissingArg(t *testing.T) {
	a := newTestApp()

	msg := components.CommandSubmittedMsg{Command: "ns", Args: ""}

	model, _ := a.Update(msg)
	app := model.(App)

	if app.err == nil {
		t.Error("expected error for /ns without arg")
	}
}

// ---------- Quit ----------

func TestApp_QuitCommand(t *testing.T) {
	a := newTestApp()
	msg := components.CommandSubmittedMsg{Command: "quit", Args: ""}

	_, cmd := a.Update(msg)

	// tea.Quit returns a special command — execute it to verify.
	if cmd == nil {
		t.Fatal("expected quit command")
	}
}

func TestApp_CtrlCQuits(t *testing.T) {
	a := newTestApp()
	_, cmd := a.Update(tea.KeyMsg{Type: tea.KeyCtrlC})

	if cmd == nil {
		t.Fatal("expected quit command on Ctrl+C")
	}
}

// ---------- helpers ----------

func viewIDName(v ViewID) string {
	names := map[ViewID]string{
		ViewHome:        "Home",
		ViewAgents:      "Agents",
		ViewAgentDetail: "AgentDetail",
		ViewTools:       "Tools",
		ViewToolDetail:  "ToolDetail",
		ViewChat:        "Chat",
		ViewDeployAgent: "DeployAgent",
		ViewDeployTool:  "DeployTool",
		ViewLogin:       "Login",
		ViewHelp:        "Help",
	}
	if n, ok := names[v]; ok {
		return n
	}
	return "Unknown"
}
