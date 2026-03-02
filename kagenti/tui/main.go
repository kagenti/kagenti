package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui"
	"github.com/kagenti/kagenti/kagenti/tui/internal/version"
)

func main() {
	var (
		flagURL       = flag.String("url", "", "Kagenti backend URL")
		flagToken     = flag.String("token", "", "Auth token")
		flagNamespace = flag.String("namespace", "", "Default namespace")
		flagVersion   = flag.Bool("version", false, "Print version and exit")
	)
	flag.Parse()

	if *flagVersion {
		fmt.Println("kagenti-tui", version.Version)
		os.Exit(0)
	}

	cfg := config.Load(*flagURL, *flagToken, *flagNamespace)
	client := api.NewClient(cfg.URL, cfg.Token, cfg.Namespace)

	// Restore Keycloak config and refresh token from saved config
	if cfg.RefreshToken != "" {
		client.SetRefreshToken(cfg.RefreshToken)
	}
	if cfg.KeycloakURL != "" {
		client.SetKeycloakConfig(cfg.KeycloakURL, cfg.Realm, cfg.ClientID)
	}

	// Persist refreshed tokens to config file
	client.OnTokenRefresh = func(accessToken, refreshToken string) {
		saved := config.Load("", "", "")
		saved.Token = accessToken
		saved.RefreshToken = refreshToken
		_ = saved.Save()
	}

	app := ui.NewApp(client)

	p := tea.NewProgram(app, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
