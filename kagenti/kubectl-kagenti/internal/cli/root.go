// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

// Set by ldflags at release time.
var (
	Version   = "dev"
	GitCommit = "none"
)

var (
	rootNamespace          string
	rootAllNamespaces      bool
	rootOutput             string
	rootBackendDiscovery   string
)

// Execute runs the root command.
func Execute() error {
	root := &cobra.Command{
		Use:   "kagenti",
		Short: "Kagenti platform CLI (kubectl/oc plugin)",
		Long: `kubectl kagenti / oc kagenti — interact with the Kagenti control plane.

Global flags apply to subcommands that list or format API resources (stories after RHAIENG-3805).

Configuration:
  $XDG_CONFIG_HOME/kagenti/config.yaml (or ~/.config/kagenti/config.yaml)

  backend_url: https://...          # optional if kubectl can discover the API
  backend_discovery: auto          # auto | route | service (see README)
  backend_namespace: kagenti-system
  token_path: ~/.config/kagenti/token

  When backend_url is unset: OpenShift Route kagenti-api in kagenti-system (HTTPS),
  else Service kagenti-backend cluster URL (HTTP). Use backend_discovery: service
  to skip the route and use the in-cluster service base URL.

Environment:
  KAGENTI_BACKEND_URL        explicit API base URL
  KAGENTI_BACKEND_DISCOVERY  auto | route | service
  KAGENTI_BACKEND_NAMESPACE  namespace for route/service lookup
  KAGENTI_KUBECTL            path to kubectl/oc binary
  KAGENTI_TOKEN              bearer JWT
  KAGENTI_TOKEN_PATH         path to JWT file
  KAGENTI_KEYCLOAK_URL      optional IdP base (browser login)
  KAGENTI_OIDC_LOCAL_PORT   localhost callback port (default 8250)`,
		SilenceUsage: true,
		RunE: func(cmd *cobra.Command, _ []string) error {
			return cmd.Help()
		},
	}
	root.PersistentFlags().StringVarP(&rootNamespace, "namespace", "n", "", "Kubernetes namespace scope")
	root.PersistentFlags().BoolVarP(&rootAllNamespaces, "all-namespaces", "A", false, "If true, operate across all namespaces")
	root.PersistentFlags().StringVarP(&rootOutput, "output", "o", "", "Output format: json|yaml|wide (default: plain text)")
	root.PersistentFlags().StringVar(&rootBackendDiscovery, "backend-discovery", "", "Discover API URL: auto (route then service), route, or service")

	root.AddCommand(authCmd(), versionCmd())
	return root.Execute()
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print version information",
		Run: func(cmd *cobra.Command, _ []string) {
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "kubectl-kagenti %s (%s)\n", Version, GitCommit)
		},
	}
}

