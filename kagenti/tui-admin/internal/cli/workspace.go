package cli

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
)

func newWorkspaceCmd(ctx *AdminContext) *cobra.Command {
	var (
		namespace string
		localDir  string
		configRef string
	)

	cmd := &cobra.Command{
		Use:   "workspace",
		Short: "Download files from agent workspaces to local directory",
		Long: `Download files from sandbox agent workspaces (PVC-backed) to a local
directory. Files are organized under configs/custom/<config-ref>/ by default.

The workspace is per-session — each agent session has its own workspace
directory inside the pod's PVC mount.`,
	}

	downloadCmd := &cobra.Command{
		Use:   "download <agent> [remote-path]",
		Short: "Download files from an agent workspace to local dir",
		Example: `  # Download all workspace files
  kagenti-admin workspace download sandbox-legion

  # Download specific file
  kagenti-admin workspace download sandbox-legion output/report.md

  # Download to custom local dir with config prefix
  kagenti-admin workspace download sandbox-legion --config-ref my-experiment
  # → saves to configs/custom/my-experiment/workspace/...

  # Download to arbitrary local dir
  kagenti-admin workspace download sandbox-legion --local-dir /tmp/results`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			agentName := args[0]
			remotePath := ""
			if len(args) > 1 {
				remotePath = args[1]
			}

			// Resolve local destination
			destDir := localDir
			if destDir == "" {
				repoRoot, err := ctx.getRepoRoot()
				if err != nil {
					repoRoot = "."
				}
				prefix := configRef
				if prefix == "" {
					prefix = agentName
				}
				destDir = filepath.Join(repoRoot, "kagenti", "tui-admin", "configs", "custom", prefix, "workspace")
			}

			if err := os.MkdirAll(destDir, 0o755); err != nil {
				return fmt.Errorf("create local dir: %w", err)
			}

			ns := namespace
			if ns == "" {
				ns = "team1"
			}

			return downloadWorkspace(ctx, cmd, ns, agentName, remotePath, destDir)
		},
	}

	downloadCmd.Flags().StringVarP(&namespace, "namespace", "n", "team1", "Agent namespace")
	downloadCmd.Flags().StringVar(&localDir, "local-dir", "", "Local directory (default: configs/custom/<ref>/workspace/)")
	downloadCmd.Flags().StringVar(&configRef, "config-ref", "", "Config reference name for organizing downloads")

	listCmd := &cobra.Command{
		Use:   "list <agent>",
		Short: "List files in an agent workspace",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ns := namespace
			if ns == "" {
				ns = "team1"
			}
			return listWorkspace(ctx, cmd, ns, args[0])
		},
	}

	listCmd.Flags().StringVarP(&namespace, "namespace", "n", "team1", "Agent namespace")

	cmd.AddCommand(downloadCmd, listCmd)
	return cmd
}

func downloadWorkspace(ctx *AdminContext, cmd *cobra.Command, namespace, agent, remotePath, destDir string) error {
	r := ctx.getRunner()

	// Find the agent pod
	result, err := r.RunSilent(context.Background(), "kubectl", "get", "pods",
		"-n", namespace, "-l", fmt.Sprintf("app.kubernetes.io/name=%s", agent),
		"-o", "jsonpath={.items[0].metadata.name}")
	if err != nil || result.Stdout == "" {
		return fmt.Errorf("agent pod %q not found in namespace %s", agent, namespace)
	}
	podName := strings.TrimSpace(result.Stdout)

	// Determine source path inside the pod
	srcPath := "/workspace"
	if remotePath != "" {
		srcPath = filepath.Join(srcPath, remotePath)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Downloading from %s:%s → %s\n", podName, srcPath, destDir)

	// Use kubectl cp to download
	_, err = r.Run(context.Background(), "kubectl", "cp",
		fmt.Sprintf("%s/%s:%s", namespace, podName, srcPath),
		destDir)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Downloaded to %s\n", destDir)
	return nil
}

func listWorkspace(ctx *AdminContext, cmd *cobra.Command, namespace, agent string) error {
	r := ctx.getRunner()

	result, err := r.RunSilent(context.Background(), "kubectl", "get", "pods",
		"-n", namespace, "-l", fmt.Sprintf("app.kubernetes.io/name=%s", agent),
		"-o", "jsonpath={.items[0].metadata.name}")
	if err != nil || result.Stdout == "" {
		return fmt.Errorf("agent pod %q not found in namespace %s", agent, namespace)
	}
	podName := strings.TrimSpace(result.Stdout)

	fmt.Fprintf(cmd.OutOrStdout(), "Workspace files for %s (%s/%s):\n\n", agent, namespace, podName)

	_, err = r.Run(context.Background(), "kubectl", "exec",
		"-n", namespace, podName, "-c", "agent", "--",
		"find", "/workspace", "-type", "f", "-printf", "%T+ %s %p\n")
	if err != nil {
		// Fallback: try ls
		_, err = r.Run(context.Background(), "kubectl", "exec",
			"-n", namespace, podName, "-c", "agent", "--",
			"ls", "-laR", "/workspace")
	}
	return err
}
