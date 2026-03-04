package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

func newToolsCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "tools",
		Short: "List tools",
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			resp, err := ctx.Client.ListTools(ns)
			if err != nil {
				return fmt.Errorf("listing tools: %w", err)
			}

			if ctx.Output == "json" {
				return printJSON(resp)
			}

			headers := []string{"NAME", "NAMESPACE", "STATUS", "PROTOCOL", "WORKLOAD"}
			var rows [][]string
			for _, t := range resp.Items {
				rows = append(rows, []string{
					t.Name, t.Namespace, t.Status,
					t.Labels.Protocol, t.WorkloadType,
				})
			}
			printTable(headers, rows)
			return nil
		},
	}
}

func newToolCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "tool <name>",
		Short: "Show tool details",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			detail, err := ctx.Client.GetTool(ns, args[0])
			if err != nil {
				return fmt.Errorf("getting tool %q: %w", args[0], err)
			}
			return printJSON(detail)
		},
	}
}
