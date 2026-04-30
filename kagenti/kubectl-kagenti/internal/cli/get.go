// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
	"github.com/spf13/cobra"
)

func getCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "get",
		Short: "Display API resources (agents, …)",
	}
	c.AddCommand(getAgentsCmd())
	return c
}

func getAgentsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "agents",
		Short: "List agents (GET /api/v1/agents; -A uses kagenti-enabled namespaces unless --enabled-only=false)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			var items []client.AgentSummary
			showNS := rootAllNamespaces
			if rootAllNamespaces {
				nsResp, err := client.ListNamespaces(ctx, base, token, rootEnabledOnly)
				if err != nil {
					return err
				}
				for _, ns := range nsResp.Namespaces {
					ar, err := client.ListAgents(ctx, base, token, ns)
					if err != nil {
						return fmt.Errorf("namespace %q: %w", ns, err)
					}
					items = append(items, ar.Items...)
				}
			} else {
				ns := rootNamespace
				if ns == "" {
					ns, err = kube.CurrentNamespace(ctx)
					if err != nil {
						return err
					}
				}
				ar, err := client.ListAgents(ctx, base, token, ns)
				if err != nil {
					return err
				}
				items = ar.Items
			}
			return writeAgentList(cmd.OutOrStdout(), rootOutput, items, showNS)
		},
	}
}
