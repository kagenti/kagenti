// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"fmt"
	"os"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
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
	rootLogLevel           int
	rootEnabledOnly        bool
)

// Execute runs the root command.
func Execute() error {
	root := &cobra.Command{
		Use:   "kagenti",
		Short: "Kagenti platform CLI (kubectl/oc plugin)",
		Long: `kubectl kagenti / oc kagenti — interact with the Kagenti control plane.

Global flags scope list/describe/deploy/build (3806 read path, 3807 deploy + Shipwright).

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
  KAGENTI_OIDC_LOCAL_PORT   localhost callback port (default 8250)

  --loglevel=9 (or -v=9)    log each HTTP request start/end to stderr`,
		SilenceUsage: true,
		PersistentPreRun: func(_ *cobra.Command, _ []string) {
			lvl := rootLogLevel
			if lvl == 0 {
				_, _ = fmt.Sscanf(os.Getenv("KAGENTI_LOGLEVEL"), "%d", &lvl)
			}
			client.SetLogLevel(lvl)
		},
		RunE: func(cmd *cobra.Command, _ []string) error {
			return cmd.Help()
		},
	}
	root.PersistentFlags().StringVarP(&rootNamespace, "namespace", "n", "", "Kubernetes namespace scope")
	root.PersistentFlags().BoolVarP(&rootAllNamespaces, "all-namespaces", "A", false, "If true, operate across all namespaces")
	root.PersistentFlags().StringVarP(&rootOutput, "output", "o", "", "Output format: json|yaml|wide (default: plain text)")
	root.PersistentFlags().StringVar(&rootBackendDiscovery, "backend-discovery", "", "Discover API URL: auto (route then service), route, or service")
	root.PersistentFlags().IntVarP(&rootLogLevel, "loglevel", "v", 0, "Log level: 9 = trace HTTP to stderr (same idea as kubectl -v=9). Overrides with KAGENTI_LOGLEVEL.")
	root.PersistentFlags().BoolVar(&rootEnabledOnly, "enabled-only", true, "With -A, only namespaces labeled kagenti-enabled (default true). Use --enabled-only=false to scan all API-visible namespaces")

	root.AddCommand(authCmd(), versionCmd(), getCmd(), describeCmd(), mcpCmd(), deployCmd(), buildCmd())
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

