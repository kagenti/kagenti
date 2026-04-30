// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"text/tabwriter"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"gopkg.in/yaml.v3"
)

func validateOutput(o string) error {
	if o == "" {
		return nil
	}
	switch o {
	case "json", "yaml", "wide":
		return nil
	default:
		return fmt.Errorf("invalid -o/--output %q (use json, yaml, or wide)", o)
	}
}

func writeUserInfo(w io.Writer, o string, u *client.UserInfo) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(u)
	case "yaml":
		b, err := yaml.Marshal(u)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	case "wide":
		email := ""
		if u.Email != nil {
			email = *u.Email
		}
		_, err := fmt.Fprintf(w, "USERNAME\tEMAIL\tROLES\tAUTHENTICATED\n%s\t%s\t%s\t%v\n",
			u.Username, email, strings.Join(u.Roles, ","), u.Authenticated)
		return err
	default:
		_, err := fmt.Fprintf(w, "User: %s  authenticated=%v  roles=[%s]\n",
			u.Username, u.Authenticated, strings.Join(u.Roles, ", "))
		return err
	}
}

func truncate(s string, max int) string {
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.TrimSpace(s)
	if max <= 0 || len(s) <= max {
		return s
	}
	return s[:max-3] + "..."
}

// writeAgentList prints agents as json, yaml, or table.
func writeAgentList(w io.Writer, o string, items []client.AgentSummary, showNamespace bool) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(map[string]any{"items": items})
	case "yaml":
		b, err := yaml.Marshal(map[string]any{"items": items})
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	case "wide":
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		if showNamespace {
			_, _ = fmt.Fprintln(tw, "NAMESPACE\tNAME\tSTATUS\tWORKLOAD\tDESCRIPTION")
			for _, a := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\n",
					a.Namespace, a.Name, a.Status, a.WorkloadType, truncate(a.Description, 64))
			}
		} else {
			_, _ = fmt.Fprintln(tw, "NAME\tSTATUS\tWORKLOAD\tDESCRIPTION")
			for _, a := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\n",
					a.Name, a.Status, a.WorkloadType, truncate(a.Description, 64))
			}
		}
		return tw.Flush()
	default:
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		if showNamespace {
			_, _ = fmt.Fprintln(tw, "NAMESPACE\tNAME\tSTATUS\tWORKLOAD")
			for _, a := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\n", a.Namespace, a.Name, a.Status, a.WorkloadType)
			}
		} else {
			_, _ = fmt.Fprintln(tw, "NAME\tSTATUS\tWORKLOAD")
			for _, a := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\n", a.Name, a.Status, a.WorkloadType)
			}
		}
		return tw.Flush()
	}
}

// writeToolList prints MCP tools as json, yaml, or table.
func writeToolList(w io.Writer, o string, items []client.ToolSummary, showNamespace bool) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(map[string]any{"items": items})
	case "yaml":
		b, err := yaml.Marshal(map[string]any{"items": items})
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	case "wide":
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		if showNamespace {
			_, _ = fmt.Fprintln(tw, "NAMESPACE\tNAME\tSTATUS\tWORKLOAD\tDESCRIPTION")
			for _, t := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\n",
					t.Namespace, t.Name, t.Status, t.WorkloadType, truncate(t.Description, 64))
			}
		} else {
			_, _ = fmt.Fprintln(tw, "NAME\tSTATUS\tWORKLOAD\tDESCRIPTION")
			for _, t := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\n",
					t.Name, t.Status, t.WorkloadType, truncate(t.Description, 64))
			}
		}
		return tw.Flush()
	default:
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		if showNamespace {
			_, _ = fmt.Fprintln(tw, "NAMESPACE\tNAME\tSTATUS\tWORKLOAD")
			for _, t := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\n", t.Namespace, t.Name, t.Status, t.WorkloadType)
			}
		} else {
			_, _ = fmt.Fprintln(tw, "NAME\tSTATUS\tWORKLOAD")
			for _, t := range items {
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\n", t.Name, t.Status, t.WorkloadType)
			}
		}
		return tw.Flush()
	}
}
