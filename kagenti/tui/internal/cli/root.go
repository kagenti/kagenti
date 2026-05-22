// Package cli implements the non-interactive CLI mode for kagenti.
// When no subcommand is given, the interactive TUI is launched.
package cli

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui/internal/ui"
	"github.com/kagenti/kagenti/kagenti/tui/internal/version"
)

// CLIContext holds shared state for all CLI subcommands.
type CLIContext struct {
	Client *api.Client
	Config *config.Config
	Output string // "table" or "json"
}

// newClientFromConfig creates an API client from a resolved config, wiring
// Keycloak refresh tokens and the OnTokenRefresh persistence callback.
func newClientFromConfig(cfg *config.Config) *api.Client {
	client := api.NewClient(cfg.URL, cfg.Token, cfg.Namespace)

	if cfg.RefreshToken != "" {
		client.SetRefreshToken(cfg.RefreshToken)
	}
	if cfg.KeycloakURL != "" {
		client.SetKeycloakConfig(cfg.KeycloakURL, cfg.Realm, cfg.ClientID)
	}

	client.OnTokenRefresh = func(accessToken, refreshToken string) {
		saved := config.Load("", "", "")
		saved.Token = accessToken
		saved.RefreshToken = refreshToken
		_ = saved.Save()
	}

	return client
}

// NewRootCmd creates the root cobra command with all subcommands.
func NewRootCmd() *cobra.Command {
	var (
		flagURL       string
		flagToken     string
		flagNamespace string
		flagOutput    string
	)

	ctx := &CLIContext{}

	root := &cobra.Command{
		Use:   "kagenti",
		Short: "Kagenti CLI — deploy and manage AI agents",
		Long:  "Kagenti is a cloud-native middleware platform for deploying and orchestrating AI agents.\nRun without a subcommand to launch the interactive TUI.",
		// SilenceUsage prevents cobra from printing usage on every error.
		SilenceUsage: true,
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			// Skip client init for commands that don't need it.
			if cmd.Name() == "version" {
				return nil
			}

			cfg := config.Load(flagURL, flagToken, flagNamespace)
			ctx.Client = newClientFromConfig(cfg)
			ctx.Config = cfg
			ctx.Output = flagOutput
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			// No subcommand → launch interactive TUI.
			// PersistentPreRunE has already populated ctx.Client.
			app := ui.NewApp(ctx.Client)
			p := tea.NewProgram(app, tea.WithAltScreen())
			if _, err := p.Run(); err != nil {
				return err
			}
			return nil
		},
	}

	root.PersistentFlags().StringVar(&flagURL, "url", "", "Kagenti backend URL")
	root.PersistentFlags().StringVar(&flagToken, "token", "", "Auth token")
	root.PersistentFlags().StringVarP(&flagNamespace, "namespace", "n", "", "Namespace")
	root.PersistentFlags().StringVarP(&flagOutput, "output", "o", "table", "Output format: table or json")

	root.AddCommand(
		newVersionCmd(),
		newAgentsCmd(ctx),
		newAgentCmd(ctx),
		newToolsCmd(ctx),
		newToolCmd(ctx),
		newChatCmd(ctx),
		newDeployCmd(ctx),
		newDeleteCmd(ctx),
		newLoginCmd(ctx),
		newLogoutCmd(ctx),
		newStatusCmd(ctx),
	)

	return root
}

func newVersionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print the version",
		RunE: func(cmd *cobra.Command, args []string) error {
			fmt.Fprintln(cmd.OutOrStdout(), "kagenti", version.Version)
			return nil
		},
	}
}
