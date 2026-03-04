package views

import (
	"fmt"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/helpers"
)

func init() {
	// Prevent tests from opening a real browser.
	helpers.OpenBrowser = func(url string) {}
}

func TestLoginView_InitialState(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	if v.state != "loading" {
		t.Errorf("expected initial state='loading', got %q", v.state)
	}
}

func TestLoginView_HappyPathFlow(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	// Step 1: Auth config loaded (auth enabled) → stays loading (waiting for device code).
	v, _ = v.Update(authConfigLoadedMsg{
		config: &api.AuthConfigResponse{
			Enabled:     true,
			KeycloakURL: "http://keycloak.test",
			Realm:       "test-realm",
			ClientID:    "test-client",
		},
	})
	if v.state != "loading" {
		t.Errorf("after authConfigLoaded: expected state='loading', got %q", v.state)
	}
	if v.keycloakURL != "http://keycloak.test" {
		t.Errorf("expected keycloakURL stored, got %q", v.keycloakURL)
	}
	if v.realm != "test-realm" {
		t.Errorf("expected realm stored, got %q", v.realm)
	}
	if v.clientID != "test-client" {
		t.Errorf("expected clientID stored, got %q", v.clientID)
	}

	// Step 2: Device code received → transitions to "prompt".
	v, _ = v.Update(deviceCodeMsg{
		dc: &api.DeviceCodeResponse{
			DeviceCode:              "dev-code-123",
			UserCode:                "ABCD-EFGH",
			VerificationURIComplete: "http://keycloak.test/device?code=ABCD-EFGH",
			Interval:                5,
			CodeVerifier:            "pkce-verifier",
		},
	})
	if v.state != "prompt" {
		t.Errorf("after deviceCode: expected state='prompt', got %q", v.state)
	}
	if v.userCode != "ABCD-EFGH" {
		t.Errorf("expected userCode='ABCD-EFGH', got %q", v.userCode)
	}
	if v.verifyURL != "http://keycloak.test/device?code=ABCD-EFGH" {
		t.Errorf("expected verifyURL set, got %q", v.verifyURL)
	}
	if v.deviceCode != "dev-code-123" {
		t.Errorf("expected deviceCode stored, got %q", v.deviceCode)
	}
	if v.codeVerifier != "pkce-verifier" {
		t.Errorf("expected codeVerifier stored, got %q", v.codeVerifier)
	}
	if v.pollInterval != 5 {
		t.Errorf("expected pollInterval=5, got %d", v.pollInterval)
	}

	// Step 3: User presses Enter → transitions to "polling".
	v, cmd := v.Update(tea.KeyMsg{Type: tea.KeyEnter})
	if v.state != "polling" {
		t.Errorf("after Enter: expected state='polling', got %q", v.state)
	}
	if cmd == nil {
		t.Error("expected polling command after Enter")
	}

	// Step 4: Token received → transitions to "done".
	v, _ = v.Update(loginCompleteMsg{
		tokenResp: &api.TokenResponse{
			AccessToken:  "access-token-xyz",
			RefreshToken: "refresh-token-xyz",
		},
	})
	if v.state != "done" {
		t.Errorf("after loginComplete: expected state='done', got %q", v.state)
	}
}

func TestLoginView_DisabledAuth(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	v, _ = v.Update(authConfigLoadedMsg{
		config: &api.AuthConfigResponse{Enabled: false},
	})

	if v.state != "disabled" {
		t.Errorf("expected state='disabled' for auth not enabled, got %q", v.state)
	}
}

func TestLoginView_AuthConfigError(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	v, _ = v.Update(authConfigLoadedMsg{
		err: fmt.Errorf("connection refused"),
	})

	if v.state != "error" {
		t.Errorf("expected state='error', got %q", v.state)
	}
	if v.err == nil || v.err.Error() != "connection refused" {
		t.Errorf("expected err='connection refused', got %v", v.err)
	}
}

func TestLoginView_DeviceCodeError(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	// First get past auth config.
	v, _ = v.Update(authConfigLoadedMsg{
		config: &api.AuthConfigResponse{
			Enabled:     true,
			KeycloakURL: "http://keycloak.test",
			Realm:       "realm",
			ClientID:    "client",
		},
	})

	// Device code request fails.
	v, _ = v.Update(deviceCodeMsg{
		err: fmt.Errorf("keycloak unreachable"),
	})

	if v.state != "error" {
		t.Errorf("expected state='error', got %q", v.state)
	}
	if v.err == nil || v.err.Error() != "keycloak unreachable" {
		t.Errorf("expected err='keycloak unreachable', got %v", v.err)
	}
}

func TestLoginView_LoginCompleteError(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)

	// Advance to polling state.
	v.state = "polling"

	v, _ = v.Update(loginCompleteMsg{
		err: fmt.Errorf("authorization_pending timeout"),
	})

	if v.state != "error" {
		t.Errorf("expected state='error', got %q", v.state)
	}
}

func TestLoginView_EscFromTerminalStates(t *testing.T) {
	terminalStates := []string{"done", "error", "disabled"}

	for _, state := range terminalStates {
		t.Run("esc_from_"+state, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewLoginView(client)
			v.state = state
			if state == "error" {
				v.err = fmt.Errorf("test")
			}

			_, cmd := v.Update(tea.KeyMsg{Type: tea.KeyEsc})

			if cmd == nil {
				t.Fatal("expected navigation command on Esc")
			}
			msg := cmd()
			nav, ok := msg.(NavigateMsg)
			if !ok {
				t.Fatalf("expected NavigateMsg, got %T", msg)
			}
			if nav.Target != "home" {
				t.Errorf("expected navigate to 'home', got %q", nav.Target)
			}
		})
	}
}

func TestLoginView_EnterFromTerminalStates(t *testing.T) {
	for _, state := range []string{"done", "error", "disabled"} {
		t.Run("enter_from_"+state, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewLoginView(client)
			v.state = state
			if state == "error" {
				v.err = fmt.Errorf("test")
			}

			_, cmd := v.Update(tea.KeyMsg{Type: tea.KeyEnter})

			if cmd == nil {
				t.Fatal("expected navigation command on Enter")
			}
			msg := cmd()
			nav, ok := msg.(NavigateMsg)
			if !ok {
				t.Fatalf("expected NavigateMsg, got %T", msg)
			}
			if nav.Target != "home" {
				t.Errorf("expected navigate to 'home', got %q", nav.Target)
			}
		})
	}
}

func TestLoginView_PromptIgnoresNonEnterKeys(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewLoginView(client)
	v.state = "prompt"
	v.userCode = "TEST"

	// Random key should not change state.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("x")})

	if v.state != "prompt" {
		t.Errorf("expected state to remain 'prompt', got %q", v.state)
	}
}

func TestLoginView_TokenPersistence(t *testing.T) {
	client := api.NewClient("http://fake", "old-token", "team1")
	v := NewLoginView(client)
	v.keycloakURL = "http://keycloak.test"
	v.realm = "realm"
	v.clientID = "client"
	v.state = "polling"

	v, _ = v.Update(loginCompleteMsg{
		tokenResp: &api.TokenResponse{
			AccessToken:  "new-access",
			RefreshToken: "new-refresh",
		},
	})

	// Verify the client was updated with new tokens.
	if client.Token != "new-access" {
		t.Errorf("expected client token='new-access', got %q", client.Token)
	}
	if client.RefreshToken != "new-refresh" {
		t.Errorf("expected client refresh token='new-refresh', got %q", client.RefreshToken)
	}
}

func TestLoginView_ViewRendersAllStates(t *testing.T) {
	tests := []struct {
		name     string
		state    string
		setup    func(*LoginView)
		contains []string
	}{
		{
			name:     "loading",
			state:    "loading",
			contains: []string{"Loading"},
		},
		{
			name:  "disabled",
			state: "disabled",
			contains: []string{
				"not enabled",
				"No login required",
			},
		},
		{
			name:  "prompt",
			state: "prompt",
			setup: func(v *LoginView) {
				v.userCode = "ABCD-EFGH"
				v.verifyURL = "http://keycloak.test/device"
			},
			contains: []string{
				"ABCD-EFGH",
				"http://keycloak.test/device",
				"Enter",
			},
		},
		{
			name:     "polling",
			state:    "polling",
			contains: []string{"Waiting", "browser"},
		},
		{
			name:     "done",
			state:    "done",
			contains: []string{"successful", "tui.yaml"},
		},
		{
			name:  "error",
			state: "error",
			setup: func(v *LoginView) {
				v.err = fmt.Errorf("something broke")
			},
			contains: []string{"failed", "something broke"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewLoginView(client)
			v.state = tc.state
			if tc.setup != nil {
				tc.setup(&v)
			}

			view := v.View()
			for _, s := range tc.contains {
				if !strings.Contains(view, s) {
					t.Errorf("expected view to contain %q, got:\n%s", s, view)
				}
			}
		})
	}
}
