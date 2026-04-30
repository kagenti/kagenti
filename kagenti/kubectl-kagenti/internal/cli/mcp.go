// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
	"github.com/spf13/cobra"
)

func mcpCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "mcp",
		Short: "MCP tool servers (GET /api/v1/tools)",
	}
	c.AddCommand(mcpListCmd())
	return c
}

func mcpListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List MCP tool deployments (GET /api/v1/tools; -A respects --enabled-only, default true)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			var items []client.ToolSummary
			showNS := rootAllNamespaces
			if rootAllNamespaces {
				nsResp, err := client.ListNamespaces(ctx, base, token, rootEnabledOnly)
				if err != nil {
					return err
				}
				for _, ns := range nsResp.Namespaces {
					tr, err := client.ListTools(ctx, base, token, ns)
					if err != nil {
						return fmt.Errorf("namespace %q: %w", ns, err)
					}
					items = append(items, tr.Items...)
				}
			} else {
				ns := rootNamespace
				if ns == "" {
					ns, err = kube.CurrentNamespace(ctx)
					if err != nil {
						return err
					}
				}
				tr, err := client.ListTools(ctx, base, token, ns)
				if err != nil {
					return err
				}
				items = tr.Items
			}
			return writeToolList(cmd.OutOrStdout(), rootOutput, items, showNS)
		},
	}
}
