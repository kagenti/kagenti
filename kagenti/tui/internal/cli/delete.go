package cli

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
)

// confirmDelete prompts the user to confirm a destructive action.
// Returns true if the user confirms or if yes is already set.
var confirmDelete = func(kind, name, namespace string) bool {
	fmt.Fprintf(os.Stderr, "Delete %s '%s' in namespace '%s'? [y/N]: ", kind, name, namespace)
	reader := bufio.NewReader(os.Stdin)
	line, _ := reader.ReadString('\n')
	return strings.TrimSpace(strings.ToLower(line)) == "y"
}

func newDeleteCmd(ctx *CLIContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "delete",
		Short: "Delete an agent or tool",
	}

	cmd.PersistentFlags().BoolP("yes", "y", false, "Skip confirmation prompt")

	cmd.AddCommand(
		newDeleteAgentCmd(ctx),
		newDeleteToolCmd(ctx),
	)

	return cmd
}

func newDeleteAgentCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "agent <name>",
		Short: "Delete an agent",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			yes, _ := cmd.Flags().GetBool("yes")
			if !yes && !confirmDelete("agent", args[0], ns) {
				fmt.Fprintln(os.Stderr, "Aborted.")
				return nil
			}
			resp, err := ctx.Client.DeleteAgent(ns, args[0])
			if err != nil {
				return fmt.Errorf("deleting agent %q: %w", args[0], err)
			}
			if !resp.Success {
				return fmt.Errorf("delete failed: %s", resp.Message)
			}
			fmt.Printf("Agent '%s' deleted\n", args[0])
			return nil
		},
	}
}

func newDeleteToolCmd(ctx *CLIContext) *cobra.Command {
	return &cobra.Command{
		Use:   "tool <name>",
		Short: "Delete a tool",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			yes, _ := cmd.Flags().GetBool("yes")
			if !yes && !confirmDelete("tool", args[0], ns) {
				fmt.Fprintln(os.Stderr, "Aborted.")
				return nil
			}
			resp, err := ctx.Client.DeleteTool(ns, args[0])
			if err != nil {
				return fmt.Errorf("deleting tool %q: %w", args[0], err)
			}
			if !resp.Success {
				return fmt.Errorf("delete failed: %s", resp.Message)
			}
			fmt.Printf("Tool '%s' deleted\n", args[0])
			return nil
		},
	}
}
