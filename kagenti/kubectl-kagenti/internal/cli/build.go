// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

func buildCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "build",
		Short: "Git + Shipwright agent builds (RHAIENG-3807)",
		Long: `Git-based agents use Shipwright: the API creates Build + BuildRun, then you wait and finalize.

  1) kubectl kagenti build create AGENT -n NAMESPACE --git-url URL [...]
  2) kubectl kagenti build status AGENT   # or: build wait AGENT
  3) kubectl kagenti build finalize AGENT   # after BuildRun Succeeded

Endpoints: POST /api/v1/agents (source), GET .../shipwright-build-info,
POST .../finalize-shipwright-build, GET /api/v1/agents/build-strategies.

Requires operator role for create/finalize; viewer for status/strategies.`,
	}
	c.AddCommand(
		buildListCmd(),
		buildCreateCmd(),
		buildStatusCmd(),
		buildWaitCmd(),
		buildFinalizeCmd(),
		buildListStrategiesCmd(),
	)
	return c
}

func buildListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List Shipwright Builds for agents (GET /api/v1/agents/shipwright-builds)",
		Long: `Lists Build CRs labeled for agents in the namespace (-n) or across all kagenti-enabled
namespaces (-A, same idea as get agents).`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			var ns string
			allNS := rootAllNamespaces
			if !allNS {
				ns = rootNamespace
				if ns == "" {
					ns, err = kube.CurrentNamespace(cmd.Context())
					if err != nil {
						return err
					}
				}
			}
			resp, err := client.ListAgentShipwrightBuilds(cmd.Context(), base, token, ns, allNS)
			if err != nil {
				return err
			}
			return writeBuildList(cmd.OutOrStdout(), rootOutput, resp.Items, allNS)
		},
	}
}

func buildCreateCmd() *cobra.Command {
	var (
		gitURL, gitBranch, gitPath, imageTag string
		registryURL, registrySecret          string
		startCommand                         string
		buildStrategy, dockerfile            string
		buildTimeout                         string
		buildArgs                            []string
		protocol, framework                  string
		workloadType                         string
		createRoute                          bool
		noAuthBridge                         bool
	)
	c := &cobra.Command{
		Use:   "create NAME",
		Short: "Start Shipwright build from git (POST /api/v1/agents, deploymentMethod=source)",
		Long: `Creates Shipwright Build + BuildRun. Poll with "build status" or "build wait", then "build finalize".

Required: --git-url. Optional: --git-branch (default main), --git-path, --image-tag,
--registry-url, --registry-secret, --build-strategy, --dockerfile, --build-timeout,
repeatable --build-arg KEY=VAL.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			if gitURL == "" {
				return fmt.Errorf("--git-url is required")
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
			req := &client.CreateAgentRequest{
				Name:             name,
				Namespace:        ns,
				DeploymentMethod: "source",
				GitURL:           gitURL,
				GitBranch:        gitBranch,
				GitPath:          gitPath,
				ImageTag:         imageTag,
				Protocol:         protocol,
				Framework:        framework,
				WorkloadType:     workloadType,
				CreateHTTPRoute:  createRoute,
			}
			if registryURL != "" {
				req.RegistryURL = &registryURL
			}
			if registrySecret != "" {
				req.RegistrySecret = &registrySecret
			}
			if startCommand != "" {
				req.StartCommand = &startCommand
			}
			if noAuthBridge {
				f := false
				req.AuthBridgeEnabled = &f
			}
			if buildStrategy != "" || dockerfile != "" || buildTimeout != "" || len(buildArgs) > 0 {
				sc := &client.ShipwrightConfigJSON{}
				if buildStrategy != "" {
					sc.BuildStrategy = &buildStrategy
				}
				if dockerfile != "" {
					sc.Dockerfile = dockerfile
				}
				if buildTimeout != "" {
					sc.BuildTimeout = buildTimeout
				}
				if len(buildArgs) > 0 {
					sc.BuildArgs = buildArgs
				}
				req.ShipwrightConfig = sc
			}
			resp, err := client.CreateAgent(cmd.Context(), base, token, req)
			if err != nil {
				return err
			}
			return writeDeployResult(cmd, rootOutput, resp)
		},
	}
	c.Flags().StringVar(&gitURL, "git-url", "", "Git repository URL (required)")
	c.Flags().StringVar(&gitBranch, "git-branch", "main", "Git branch or revision")
	c.Flags().StringVar(&gitPath, "git-path", "", "Path inside repo (Dockerfile context)")
	c.Flags().StringVar(&imageTag, "image-tag", "v0.0.1", "Output image tag")
	c.Flags().StringVar(&registryURL, "registry-url", "", "Push registry URL")
	c.Flags().StringVar(&registrySecret, "registry-secret", "", "Secret for registry push")
	c.Flags().StringVar(&startCommand, "start-command", "", "Container start command override")
	c.Flags().StringVar(&buildStrategy, "build-strategy", "", "ClusterBuildStrategy name")
	c.Flags().StringVar(&dockerfile, "dockerfile", "", "Dockerfile path in context")
	c.Flags().StringVar(&buildTimeout, "build-timeout", "", "Build timeout duration")
	c.Flags().StringSliceVar(&buildArgs, "build-arg", nil, "Build arg KEY=VAL (repeatable)")
	c.Flags().StringVar(&protocol, "protocol", "a2a", "Agent protocol")
	c.Flags().StringVar(&framework, "framework", "LangGraph", "Framework")
	c.Flags().StringVar(&workloadType, "workload-type", "deployment", "Target workload type after finalize")
	c.Flags().BoolVar(&createRoute, "create-http-route", false, "Create route after finalize (not at build start)")
	c.Flags().BoolVar(&noAuthBridge, "no-auth-bridge", false, "Disable AuthBridge after finalize")
	return c
}

func buildStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status NAME",
		Short: "Shipwright build + latest BuildRun (GET .../shipwright-build-info)",
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
			info, err := client.GetAgentShipwrightBuildInfo(cmd.Context(), base, token, ns, args[0])
			if err != nil {
				return err
			}
			return writeBuildInfo(cmd.OutOrStdout(), rootOutput, info)
		},
	}
}

func buildWaitCmd() *cobra.Command {
	var timeout, interval time.Duration
	c := &cobra.Command{
		Use:   "wait NAME",
		Short: "Poll shipwright-build-info until BuildRun Succeeded or Failed",
		Long:  `Polls GET .../shipwright-build-info until buildRunPhase is Succeeded, Failed, or timeout.`,
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
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
			deadline := time.Now().Add(timeout)
			var lastPhase string
			for time.Now().Before(deadline) {
				info, err := client.GetAgentShipwrightBuildInfo(cmd.Context(), base, token, ns, name)
				if err != nil {
					return err
				}
				ph := strings.TrimSpace(info.BuildRunPhase)
				if ph != lastPhase {
					_, _ = fmt.Fprintf(cmd.ErrOrStderr(), "buildRunPhase: %s\n", ph)
					lastPhase = ph
				}
				switch ph {
				case "Succeeded":
					_, _ = fmt.Fprintln(cmd.OutOrStdout(), info.BuildRunOutputImage)
					return nil
				case "Failed":
					return fmt.Errorf("build failed: %s", info.BuildRunFailureMessage)
				}
				time.Sleep(interval)
			}
			return fmt.Errorf("timeout after %v (last phase %q)", timeout, lastPhase)
		},
	}
	c.Flags().DurationVar(&timeout, "timeout", 45*time.Minute, "Max wait duration")
	c.Flags().DurationVar(&interval, "interval", 15*time.Second, "Poll interval")
	return c
}

func buildFinalizeCmd() *cobra.Command {
	var (
		protocol, framework string
		createRoute         bool
		imagePullSecret     string
	)
	c := &cobra.Command{
		Use:   "finalize NAME",
		Short: "Create Deployment/Service from completed Shipwright build",
		Long: `POST /api/v1/agents/{namespace}/{name}/finalize-shipwright-build.
Call only after BuildRun phase is Succeeded (see "build status").`,
		Args: cobra.ExactArgs(1),
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
			body := &client.FinalizeShipwrightBuildRequest{}
			if protocol != "" {
				body.Protocol = &protocol
			}
			if framework != "" {
				body.Framework = &framework
			}
			if cmd.Flags().Changed("create-http-route") {
				body.CreateHTTPRoute = &createRoute
			}
			if imagePullSecret != "" {
				body.ImagePullSecret = &imagePullSecret
			}
			resp, err := client.FinalizeAgentShipwrightBuild(cmd.Context(), base, token, ns, args[0], body)
			if err != nil {
				return err
			}
			return writeDeployResult(cmd, rootOutput, resp)
		},
	}
	c.Flags().StringVar(&protocol, "protocol", "", "Override protocol (default from build annotation)")
	c.Flags().StringVar(&framework, "framework", "", "Override framework")
	c.Flags().BoolVar(&createRoute, "create-http-route", false, "Create HTTPRoute/Route on finalize")
	c.Flags().StringVar(&imagePullSecret, "image-pull-secret", "", "Image pull secret for workload")
	return c
}

func buildListStrategiesCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list-strategies",
		Short: "List ClusterBuildStrategies (GET /api/v1/agents/build-strategies)",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			resp, err := client.ListAgentBuildStrategies(cmd.Context(), base, token)
			if err != nil {
				return err
			}
			return writeStrategies(cmd.OutOrStdout(), rootOutput, resp)
		},
	}
}

func writeBuildInfo(w io.Writer, o string, info *client.AgentShipwrightBuildInfoResponse) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(info)
	case "yaml":
		b, err := yaml.Marshal(info)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	default:
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		_, _ = fmt.Fprintf(tw, "BUILD\tregistered=%v\tstrategy=%s\n", info.BuildRegistered, info.Strategy)
		_, _ = fmt.Fprintf(tw, "GIT\t%s\t@%s\tcontext=%s\n", info.GitURL, info.GitRevision, info.ContextDir)
		if info.HasBuildRun {
			_, _ = fmt.Fprintf(tw, "BUILDRUN\t%s\tphase=%s\n", info.BuildRunName, info.BuildRunPhase)
			if info.BuildRunOutputImage != "" {
				_, _ = fmt.Fprintf(tw, "IMAGE\t%s\n", info.BuildRunOutputImage)
			}
			if info.BuildRunFailureMessage != "" {
				_, _ = fmt.Fprintf(tw, "FAILURE\t%s\n", info.BuildRunFailureMessage)
			}
		} else {
			_, _ = fmt.Fprintln(tw, "BUILDRUN\t(none yet)")
		}
		return tw.Flush()
	}
}

func writeBuildList(w io.Writer, o string, items []client.AgentShipwrightBuildSummary, showNS bool) error {
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
	default:
		if len(items) == 0 {
			_, _ = fmt.Fprintln(w, "No Shipwright agent builds found.")
			return nil
		}
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		if showNS {
			_, _ = fmt.Fprintln(tw, "NAMESPACE\tNAME\tREGISTERED\tSTRATEGY\tGIT\tOUTPUT")
			for _, b := range items {
				reg := "no"
				if b.Registered {
					reg = "yes"
				}
				git := truncate(b.GitURL, 40)
				out := truncate(b.OutputImage, 50)
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%s\n",
					b.Namespace, b.Name, reg, truncate(b.Strategy, 12), git, out)
			}
		} else {
			_, _ = fmt.Fprintln(tw, "NAME\tREGISTERED\tSTRATEGY\tGIT\tOUTPUT")
			for _, b := range items {
				reg := "no"
				if b.Registered {
					reg = "yes"
				}
				_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\n",
					b.Name, reg, truncate(b.Strategy, 12), truncate(b.GitURL, 45), truncate(b.OutputImage, 55))
			}
		}
		return tw.Flush()
	}
}

func writeStrategies(w io.Writer, o string, resp *client.ClusterBuildStrategiesResponse) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(resp)
	case "yaml":
		b, err := yaml.Marshal(resp)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	default:
		tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
		_, _ = fmt.Fprintln(tw, "NAME\tDESCRIPTION")
		for _, s := range resp.Strategies {
			desc := strings.ReplaceAll(s.Description, "\n", " ")
			_, _ = fmt.Fprintf(tw, "%s\t%s\n", s.Name, truncate(desc, 80))
		}
		return tw.Flush()
	}
}
