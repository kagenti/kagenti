package views

import (
	"context"
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui/internal/helpers"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// LoginView handles the device-code login flow.
type LoginView struct {
	client    *api.Client
	width     int
	height    int
	state     string // "loading", "prompt", "polling", "done", "error", "disabled"
	userCode  string
	verifyURL string
	err       error

	saveErr error // non-nil if config save failed after successful login

	// Stored from auth config + device code for polling
	keycloakURL  string
	realm        string
	clientID     string
	deviceCode   string
	codeVerifier string
	pollInterval int
}

// NewLoginView creates a new login view.
func NewLoginView(client *api.Client) LoginView {
	return LoginView{client: client, state: "loading"}
}

// SetSize sets the view dimensions.
func (v *LoginView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type authConfigLoadedMsg struct {
	config *api.AuthConfigResponse
	err    error
}

type deviceCodeMsg struct {
	dc  *api.DeviceCodeResponse
	err error
}

type loginCompleteMsg struct {
	tokenResp *api.TokenResponse
	err       error
}

// Init starts the login flow by fetching auth config.
func (v LoginView) Init() tea.Cmd {
	v.state = "loading"
	client := v.client
	return func() tea.Msg {
		cfg, err := client.GetAuthConfig()
		if err != nil {
			return authConfigLoadedMsg{err: err}
		}
		return authConfigLoadedMsg{config: cfg}
	}
}

// Update handles messages.
func (v LoginView) Update(msg tea.Msg) (LoginView, tea.Cmd) {
	switch msg := msg.(type) {
	case authConfigLoadedMsg:
		if msg.err != nil {
			v.state = "error"
			v.err = msg.err
			return v, nil
		}
		if !msg.config.Enabled {
			v.state = "disabled"
			return v, nil
		}
		// Store auth config and request device code
		v.keycloakURL = msg.config.KeycloakURL
		v.realm = msg.config.Realm
		v.clientID = msg.config.ClientID
		v.state = "loading"
		client := v.client
		cfg := msg.config
		return v, func() tea.Msg {
			dc, err := client.RequestDeviceCode(cfg.KeycloakURL, cfg.Realm, cfg.ClientID)
			if err != nil {
				return deviceCodeMsg{err: err}
			}
			return deviceCodeMsg{dc: dc}
		}

	case deviceCodeMsg:
		if msg.err != nil {
			v.state = "error"
			v.err = msg.err
			return v, nil
		}
		v.state = "prompt"
		v.userCode = msg.dc.UserCode
		v.verifyURL = msg.dc.VerificationURIComplete
		v.deviceCode = msg.dc.DeviceCode
		v.codeVerifier = msg.dc.CodeVerifier
		v.pollInterval = msg.dc.Interval

		// Auto-open browser
		helpers.OpenBrowser(v.verifyURL)

		return v, nil

	case loginCompleteMsg:
		if msg.err != nil {
			v.state = "error"
			v.err = msg.err
			return v, nil
		}
		// Set access token and refresh token on the client
		v.client.SetToken(msg.tokenResp.AccessToken)
		v.client.SetRefreshToken(msg.tokenResp.RefreshToken)
		v.client.SetKeycloakConfig(v.keycloakURL, v.realm, v.clientID)

		// Persist everything to config file
		cfg := config.Load("", "", "")
		cfg.Token = msg.tokenResp.AccessToken
		cfg.RefreshToken = msg.tokenResp.RefreshToken
		cfg.KeycloakURL = v.keycloakURL
		cfg.Realm = v.realm
		cfg.ClientID = v.clientID
		if err := cfg.Save(); err != nil {
			v.saveErr = err
		}

		v.state = "done"
		return v, nil

	case tea.KeyMsg:
		switch v.state {
		case "prompt":
			if msg.Type == tea.KeyEnter {
				// User confirmed — start polling with the stored device code
				v.state = "polling"
				client := v.client
				keycloakURL := v.keycloakURL
				realm := v.realm
				clientID := v.clientID
				deviceCode := v.deviceCode
				codeVerifier := v.codeVerifier
				interval := v.pollInterval
				return v, func() tea.Msg {
					tr, err := client.PollDeviceToken(context.TODO(), keycloakURL, realm, clientID, deviceCode, codeVerifier, interval)
					if err != nil {
						return loginCompleteMsg{err: err}
					}
					return loginCompleteMsg{tokenResp: tr}
				}
			}
		case "done", "error", "disabled":
			if msg.Type == tea.KeyEsc || msg.Type == tea.KeyEnter {
				return v, func() tea.Msg {
					return NavigateMsg{Target: "home"}
				}
			}
		}
	}
	return v, nil
}

// View renders the login view.
func (v LoginView) View() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Login") + "\n\n")

	switch v.state {
	case "loading":
		b.WriteString(theme.MutedStyle.Render("  Loading auth configuration..."))

	case "disabled":
		b.WriteString(theme.MutedStyle.Render("  Authentication is not enabled on this backend.") + "\n")
		b.WriteString(theme.MutedStyle.Render("  No login required.") + "\n\n")
		b.WriteString(theme.MutedStyle.Render("  Press Esc to return"))

	case "prompt":
		b.WriteString("  A browser window has been opened. If it didn't open, visit:\n\n")
		b.WriteString("  " + theme.CommandInputStyle.Render(v.verifyURL) + "\n\n")
		b.WriteString("  Enter the code: " + theme.TitleStyle.Render(v.userCode) + "\n\n")
		b.WriteString(theme.MutedStyle.Render("  Press Enter after authorizing in the browser"))

	case "polling":
		b.WriteString(theme.WarningStyle.Render("  Waiting for browser authorization...") + "\n")
		b.WriteString(theme.MutedStyle.Render("  Complete the login in your browser"))

	case "done":
		b.WriteString(theme.SuccessStyle.Render("  Login successful!") + "\n")
		if v.saveErr != nil {
			b.WriteString(theme.WarningStyle.Render(fmt.Sprintf("  Warning: failed to save config: %v", v.saveErr)) + "\n")
		} else {
			b.WriteString(theme.MutedStyle.Render("  Token saved to ~/.config/kagenti/tui.yaml") + "\n")
		}
		b.WriteString("\n")
		b.WriteString(theme.MutedStyle.Render("  Press Esc to return"))

	case "error":
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Login failed: %s", v.err.Error())) + "\n\n")
		b.WriteString(theme.MutedStyle.Render("  Press Esc to return"))
	}

	return b.String()
}
