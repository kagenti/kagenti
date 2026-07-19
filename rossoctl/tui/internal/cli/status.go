package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

func newStatusCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show connection and platform status",
		RunE: func(cmd *cobra.Command, args []string) error {
			type statusData struct {
				URL           string `json:"url"`
				Namespace     string `json:"namespace"`
				Connected     bool   `json:"connected"`
				AuthEnabled   bool   `json:"authEnabled"`
				Authenticated bool   `json:"authenticated"`
				Username      string `json:"username,omitempty"`
				AgentCount    int    `json:"agentCount"`
				ToolCount     int    `json:"toolCount"`
			}

			data := statusData{
				URL:       ctx.Client.BaseURL,
				Namespace: ctx.Client.Namespace,
			}

			authStatus, err := ctx.Client.GetAuthStatus()
			if err != nil {
				if ctx.Output == "json" {
					return printJSON(data)
				}
				fmt.Printf("Connection:  FAILED (%s)\n", err)
				fmt.Printf("URL:         %s\n", data.URL)
				return nil
			}
			data.Connected = true
			data.AuthEnabled = authStatus.Enabled
			data.Authenticated = authStatus.Authenticated

			if user, err := ctx.Client.GetCurrentUser(); err == nil {
				data.Username = user.Username
			}
			if agents, err := ctx.Client.ListAgents(""); err == nil {
				data.AgentCount = len(agents.Items)
			}
			if tools, err := ctx.Client.ListTools(""); err == nil {
				data.ToolCount = len(tools.Items)
			}

			if ctx.Output == "json" {
				return printJSON(data)
			}

			fmt.Printf("Connection:  Connected\n")
			fmt.Printf("URL:         %s\n", data.URL)
			fmt.Printf("Namespace:   %s\n", data.Namespace)
			if data.AuthEnabled {
				if data.Authenticated {
					auth := "Authenticated"
					if data.Username != "" && data.Username != "guest" {
						auth += fmt.Sprintf(" (%s)", data.Username)
					}
					fmt.Printf("Auth:        %s\n", auth)
				} else {
					fmt.Printf("Auth:        Not authenticated\n")
				}
			} else {
				fmt.Printf("Auth:        disabled\n")
			}
			fmt.Printf("Agents:      %d\n", data.AgentCount)
			fmt.Printf("Tools:       %d\n", data.ToolCount)
			return nil
		},
	}
}
