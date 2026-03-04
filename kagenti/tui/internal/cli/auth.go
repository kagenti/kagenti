package cli

import (
	"fmt"
	"time"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui/internal/config"
	"github.com/kagenti/kagenti/kagenti/tui/internal/helpers"
)

func newLoginCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "login",
		Short: "Authenticate via device code OAuth flow",
		RunE: func(cmd *cobra.Command, args []string) error {
			authCfg, err := ctx.Client.GetAuthConfig()
			if err != nil {
				return fmt.Errorf("fetching auth config: %w", err)
			}
			if !authCfg.Enabled {
				fmt.Println("Authentication is not enabled on this backend.")
				return nil
			}

			dc, err := ctx.Client.RequestDeviceCode(authCfg.KeycloakURL, authCfg.Realm, authCfg.ClientID)
			if err != nil {
				return fmt.Errorf("requesting device code: %w", err)
			}

			fmt.Printf("Open this URL in your browser:\n\n  %s\n\n", dc.VerificationURIComplete)
			fmt.Printf("Enter the code: %s\n\n", dc.UserCode)

			helpers.OpenBrowser(dc.VerificationURIComplete)

			fmt.Println("Waiting for browser authorization...")

			// Poll with a short delay to avoid hammering the server.
			interval := dc.Interval
			if interval < 5 {
				interval = 5
			}
			time.Sleep(time.Duration(interval) * time.Second)

			tr, err := ctx.Client.PollDeviceToken(
				authCfg.KeycloakURL, authCfg.Realm, authCfg.ClientID,
				dc.DeviceCode, dc.CodeVerifier, dc.Interval,
			)
			if err != nil {
				return fmt.Errorf("polling for token: %w", err)
			}

			// Persist tokens and Keycloak config.
			cfg := config.Load("", "", "")
			cfg.Token = tr.AccessToken
			cfg.RefreshToken = tr.RefreshToken
			cfg.KeycloakURL = authCfg.KeycloakURL
			cfg.Realm = authCfg.Realm
			cfg.ClientID = authCfg.ClientID
			if err := cfg.Save(); err != nil {
				return fmt.Errorf("saving config: %w", err)
			}

			fmt.Println("Login successful! Token saved to ~/.config/kagenti/tui.yaml")
			return nil
		},
	}
}

func newLogoutCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "logout",
		Short: "Clear saved authentication tokens",
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load("", "", "")
			cfg.Token = ""
			cfg.RefreshToken = ""
			if err := cfg.Save(); err != nil {
				return fmt.Errorf("saving config: %w", err)
			}
			fmt.Println("Logged out. Tokens cleared from ~/.config/kagenti/tui.yaml")
			return nil
		},
	}
}
