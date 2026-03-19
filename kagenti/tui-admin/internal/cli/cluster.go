package cli

import (
	"context"
	"fmt"
	"os"
	"text/tabwriter"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/cluster"
)

func newClusterCmd(ctx *AdminContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "cluster",
		Short: "Manage dev clusters (Kind, K3s, HyperShift)",
		Long:  "Create, destroy, list, and switch between Kubernetes clusters for Kagenti development and testing.",
	}

	cmd.AddCommand(
		newClusterCreateCmd(ctx),
		newClusterDestroyCmd(ctx),
		newClusterListCmd(ctx),
		newClusterUseCmd(ctx),
	)

	return cmd
}

func newClusterCreateCmd(ctx *AdminContext) *cobra.Command {
	var platform string
	var clusterName string

	cmd := &cobra.Command{
		Use:   "create",
		Short: "Create a new cluster",
		Example: `  kagenti-admin cluster create --platform kind
  kagenti-admin cluster create --platform k3s
  kagenti-admin cluster create --platform kind --name my-cluster`,
		RunE: func(cmd *cobra.Command, args []string) error {
			p := cluster.Platform(platform)
			if p == "k3s" {
				p = cluster.PlatformRancherDesktop
			}

			info, err := ctx.ClusterManager.Create(context.Background(), p, clusterName)
			if err != nil {
				return err
			}

			fmt.Fprintf(cmd.OutOrStdout(), "Cluster ready: %s (platform: %s, context: %s)\n", info.Name, info.Platform, info.Context)

			// Save kubeconfig
			kcPath, err := ctx.ClusterManager.SaveKubeconfig(context.Background(), info)
			if err == nil && kcPath != "" {
				fmt.Fprintf(cmd.OutOrStdout(), "Kubeconfig: %s\n", kcPath)
			}

			return nil
		},
	}

	cmd.Flags().StringVar(&platform, "platform", "kind", "Platform: kind, k3s, hypershift")
	cmd.Flags().StringVar(&clusterName, "name", "kagenti", "Cluster name (Kind only)")

	return cmd
}

func newClusterDestroyCmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:   "destroy [name]",
		Short: "Destroy a cluster",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := "kagenti"
			if len(args) > 0 {
				name = args[0]
			}

			// Find the cluster
			clusters, err := ctx.ClusterManager.List(context.Background())
			if err != nil {
				return err
			}

			for _, c := range clusters {
				if c.Name == name {
					return ctx.ClusterManager.Destroy(context.Background(), &c)
				}
			}

			return fmt.Errorf("cluster %q not found", name)
		},
	}
}

func newClusterListCmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all known clusters",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, args []string) error {
			clusters, err := ctx.ClusterManager.List(context.Background())
			if err != nil {
				return err
			}

			if len(clusters) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No clusters found")
				return nil
			}

			w := tabwriter.NewWriter(os.Stdout, 0, 4, 2, ' ', 0)
			fmt.Fprintln(w, "NAME\tPLATFORM\tCONTEXT\tSTATUS")
			for _, c := range clusters {
				ctx := c.Context
				if ctx == "" && c.Kubeconfig != "" {
					ctx = c.Kubeconfig
				}
				fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", c.Name, c.Platform, ctx, c.Status)
			}
			w.Flush()

			return nil
		},
	}
}

func newClusterUseCmd(ctx *AdminContext) *cobra.Command {
	return &cobra.Command{
		Use:   "use <name>",
		Short: "Switch kubectl context to a cluster",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			name := args[0]

			clusters, err := ctx.ClusterManager.List(context.Background())
			if err != nil {
				return err
			}

			for _, c := range clusters {
				if c.Name == name {
					return ctx.ClusterManager.Use(context.Background(), &c)
				}
			}

			return fmt.Errorf("cluster %q not found", name)
		},
	}
}
