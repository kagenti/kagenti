// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"encoding/json"
	"fmt"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

func describeCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "describe",
		Short: "Show detailed API resource state",
	}
	c.AddCommand(describeAgentCmd())
	return c
}

func describeAgentCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "agent NAME",
		Short: "Describe an agent (GET /api/v1/agents/{namespace}/{name})",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			ns := rootNamespace
			if ns == "" {
				ns, err = kube.CurrentNamespace(cmd.Context())
				if err != nil {
					return err
				}
			}
			name := args[0]
			body, err := client.GetAgent(cmd.Context(), base, token, ns, name)
			if err != nil {
				return err
			}
			switch rootOutput {
			case "json":
				var v any
				if err := json.Unmarshal(body, &v); err != nil {
					return err
				}
				enc := json.NewEncoder(cmd.OutOrStdout())
				enc.SetIndent("", "  ")
				return enc.Encode(v)
			case "yaml":
				var v any
				if err := json.Unmarshal(body, &v); err != nil {
					return err
				}
				b, err := yaml.Marshal(v)
				if err != nil {
					return err
				}
				_, err = cmd.OutOrStdout().Write(b)
				return err
			default:
				return writeAgentDescribeSummary(cmd.OutOrStdout(), body, rootOutput == "wide")
			}
		},
	}
}

func writeAgentDescribeSummary(w interface{ Write([]byte) (int, error) }, body []byte, wide bool) error {
	var root map[string]any
	if err := json.Unmarshal(body, &root); err != nil {
		return err
	}
	meta, _ := root["metadata"].(map[string]any)
	name, _ := meta["name"].(string)
	ns, _ := meta["namespace"].(string)
	ready, _ := root["readyStatus"].(string)
	wt, _ := root["workloadType"].(string)
	var sb []byte
	sb = fmt.Appendf(sb, "Name:         %s\n", name)
	sb = fmt.Appendf(sb, "Namespace:    %s\n", ns)
	sb = fmt.Appendf(sb, "Ready:        %s\n", ready)
	sb = fmt.Appendf(sb, "WorkloadType: %s\n", wt)
	if svc, ok := root["service"].(map[string]any); ok && svc != nil {
		sname, _ := svc["name"].(string)
		stype, _ := svc["type"].(string)
		sb = fmt.Appendf(sb, "Service:      %s (%s)\n", sname, stype)
	}
	if wide {
		if spec, ok := root["spec"].(map[string]any); ok {
			if b, err := yaml.Marshal(spec); err == nil {
				sb = append(sb, "\nSpec:\n"...)
				sb = append(sb, b...)
			}
		}
	}
	_, err := w.Write(sb)
	return err
}
