package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

func newAgentsCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "agents",
		Short: "List agents",
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			resp, err := ctx.Client.ListAgents(ns)
			if err != nil {
				return fmt.Errorf("listing agents: %w", err)
			}

			if ctx.Output == "json" {
				return printJSON(resp)
			}

			headers := []string{"NAME", "NAMESPACE", "STATUS", "FRAMEWORK", "PROTOCOL"}
			var rows [][]string
			for _, a := range resp.Items {
				rows = append(rows, []string{
					a.Name, a.Namespace, a.Status,
					a.Labels.Framework, a.Labels.Protocol,
				})
			}
			printTable(headers, rows)
			return nil
		},
	}
}

func newAgentCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "agent <name>",
		Short: "Show agent details",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			detail, err := ctx.Client.GetAgent(ns, args[0])
			if err != nil {
				return fmt.Errorf("getting agent %q: %w", args[0], err)
			}
			return printJSON(detail)
		},
	}
}
