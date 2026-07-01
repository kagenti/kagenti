package cli

import (
	"fmt"
	"regexp"
	"strconv"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/helpers"
)

// storageSizeRE matches a Kubernetes resource.Quantity in the binary
// (e.g. "5Gi") or decimal (e.g. "500M") form, plus plain byte counts.
// We intentionally accept the same shapes the K8s API server would, then
// apply a sanity range so an obvious typo like "1XB" or "0Gi" fails up
// front instead of after the manifest hits the API server.
var storageSizeRE = regexp.MustCompile(`^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?$`)

const (
	minStorageBytes int64 = 1 << 20  // 1Mi — anything smaller is almost certainly a typo
	maxStorageBytes int64 = 10 << 40 // 10Ti — well past any sensible per-agent volume
)

func validateStorageSize(size string) error {
	m := storageSizeRE.FindStringSubmatch(size)
	if m == nil {
		return fmt.Errorf(
			"--persistent-storage-size %q is not a valid Kubernetes size (e.g. 1Gi, 500Mi, 5G)",
			size,
		)
	}
	n, err := strconv.ParseFloat(m[1], 64)
	if err != nil || n <= 0 {
		return fmt.Errorf("--persistent-storage-size %q must be a positive number", size)
	}
	var unit int64 = 1
	switch m[2] {
	case "Ki":
		unit = 1 << 10
	case "Mi":
		unit = 1 << 20
	case "Gi":
		unit = 1 << 30
	case "Ti":
		unit = 1 << 40
	case "Pi":
		unit = 1 << 50
	case "Ei":
		unit = 1 << 60
	case "K":
		unit = 1_000
	case "M":
		unit = 1_000_000
	case "G":
		unit = 1_000_000_000
	case "T":
		unit = 1_000_000_000_000
	case "P":
		unit = 1_000_000_000_000_000
	case "E":
		unit = 1_000_000_000_000_000_000
	}
	bytes := int64(n * float64(unit))
	if bytes < minStorageBytes {
		return fmt.Errorf(
			"--persistent-storage-size %q is too small; minimum is 1Mi", size,
		)
	}
	if bytes > maxStorageBytes {
		return fmt.Errorf(
			"--persistent-storage-size %q is too large; maximum is 10Ti", size,
		)
	}
	return nil
}

func newDeployCmd(ctx *CLIContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "deploy",
		Short: "Deploy an agent or tool",
	}

	cmd.AddCommand(
		newDeployAgentCmd(ctx),
		newDeployToolCmd(ctx),
	)

	return cmd
}

func newDeployAgentCmd(ctx *CLIContext) *cobra.Command {
	var (
		name           string
		framework      string
		protocol       string
		deployMethod   string
		workloadType   string
		persistent     bool
		storageSize    string
		containerImage string
		gitURL         string
		gitPath        string
		gitBranch      string
		createRoute    bool
		spire          bool
		llmEnv         string
		llmModel       string
		logLevel       string
		mcpTool        string
		mcpURL         string
		envVars        []string
	)

	cmd := &cobra.Command{
		Use:   "agent",
		Short: "Deploy an agent",
		RunE: func(cmd *cobra.Command, args []string) error {
			if persistent && workloadType != "statefulset" {
				return fmt.Errorf("--persistent-storage is only supported with --workload-type statefulset")
			}
			if cmd.Flags().Changed("persistent-storage-size") && !persistent {
				return fmt.Errorf("--persistent-storage-size requires --persistent-storage")
			}
			if persistent {
				if err := validateStorageSize(storageSize); err != nil {
					return err
				}
			}

			ns, _ := cmd.Flags().GetString("namespace")
			if ns == "" {
				ns = ctx.Client.Namespace
			}

			allEnv := helpers.LLMPresetEnvVars(llmEnv, llmModel)

			// Resolve MCP_URL from tool name if not explicit.
			if mcpURL == "" && mcpTool != "" {
				tools, err := ctx.Client.ListTools(ns)
				if err == nil {
					for _, t := range tools.Items {
						if t.Name == mcpTool {
							path := "/mcp"
							if string(t.Labels.Protocol) == "sse" {
								path = "/sse"
							}
							mcpURL = fmt.Sprintf("http://%s-mcp.%s.svc.cluster.local:8000%s",
								t.Name, t.Namespace, path)
							break
						}
					}
				}
			}
			if mcpURL != "" {
				allEnv = append(allEnv, api.EnvVar{Name: "MCP_URL", Value: mcpURL})
			}
			if logLevel != "" {
				allEnv = append(allEnv, api.EnvVar{Name: "LOG_LEVEL", Value: logLevel})
			}
			for _, ev := range envVars {
				allEnv = append(allEnv, helpers.ParseEnvVars(ev)...)
			}

			req := &api.CreateAgentRequest{
				Name:              name,
				Namespace:         ns,
				Protocol:          protocol,
				Framework:         framework,
				DeploymentMethod:  deployMethod,
				WorkloadType:      workloadType,
				ContainerImage:    containerImage,
				GitURL:            gitURL,
				GitPath:           gitPath,
				GitBranch:         gitBranch,
				CreateHTTPRoute:   createRoute,
				AuthBridgeEnabled: true,
				SpireEnabled:      spire,
				EnvVars:           allEnv,
			}
			if persistent {
				req.PersistentStorage = &api.PersistentStorageConfig{
					Enabled: true,
					Size:    storageSize,
				}
			}

			resp, err := ctx.Client.CreateAgent(req)
			if err != nil {
				return fmt.Errorf("creating agent: %w", err)
			}
			if !resp.Success {
				return fmt.Errorf("agent creation failed: %s", resp.Message)
			}
			fmt.Printf("Agent '%s' created in %s\n", resp.Name, resp.Namespace)
			return nil
		},
	}

	cmd.Flags().StringVar(&name, "name", "", "Agent name (required)")
	cmd.Flags().StringVar(&framework, "framework", "LangGraph", "Framework (LangGraph, CrewAI, AG2, Custom)")
	cmd.Flags().StringVar(&protocol, "protocol", "a2a", "Protocol (a2a, mcp)")
	cmd.Flags().StringVar(&deployMethod, "deploy-method", "image", "Deployment method (image, source)")
	cmd.Flags().StringVar(&workloadType, "workload-type", "deployment", "Workload type (deployment, statefulset, job)")
	cmd.Flags().BoolVar(&persistent, "persistent-storage", false, "Enable persistent storage (statefulset only)")
	cmd.Flags().StringVar(&storageSize, "persistent-storage-size", "1Gi", "Persistent volume claim size (e.g., 1Gi, 5Gi, 10Gi)")
	cmd.Flags().StringVar(&containerImage, "container-image", "", "Container image")
	cmd.Flags().StringVar(&gitURL, "git-url", "", "Git repository URL")
	cmd.Flags().StringVar(&gitPath, "git-path", "", "Path to agent source within the repository (e.g. a2a/my_agent)")
	cmd.Flags().StringVar(&gitBranch, "git-branch", "main", "Git branch")
	cmd.Flags().BoolVar(&createRoute, "create-route", false, "Create HTTP route")
	cmd.Flags().BoolVar(&spire, "spire", false, "Enable SPIRE identity")
	cmd.Flags().StringVar(&llmEnv, "llm-env", "", "LLM environment preset (openai, ollama)")
	cmd.Flags().StringVar(&llmModel, "llm-model", "", "LLM model override")
	cmd.Flags().StringVar(&logLevel, "log-level", "", "Log level")
	cmd.Flags().StringVar(&mcpTool, "mcp-tool", "", "MCP tool name (auto-generates MCP_URL)")
	cmd.Flags().StringVar(&mcpURL, "mcp-url", "", "Explicit MCP URL override")
	cmd.Flags().StringArrayVar(&envVars, "env", nil, "Extra env var KEY=VALUE (repeatable)")
	_ = cmd.MarkFlagRequired("name")

	return cmd
}

func newDeployToolCmd(ctx *CLIContext) *cobra.Command {
	var (
		name           string
		description    string
		protocol       string
		deployMethod   string
		containerImage string
		gitURL         string
		workloadType   string
		createRoute    bool
		spire          bool
		logLevel       string
		envVars        []string
	)

	cmd := &cobra.Command{
		Use:   "tool",
		Short: "Deploy a tool",
		RunE: func(cmd *cobra.Command, args []string) error {
			ns, _ := cmd.Flags().GetString("namespace")
			if ns == "" {
				ns = ctx.Client.Namespace
			}

			var allEnv []api.EnvVar
			if logLevel != "" {
				allEnv = append(allEnv, api.EnvVar{Name: "LOG_LEVEL", Value: logLevel})
			}
			for _, ev := range envVars {
				allEnv = append(allEnv, helpers.ParseEnvVars(ev)...)
			}

			req := &api.CreateToolRequest{
				Name:             name,
				Namespace:        ns,
				Protocol:         protocol,
				Description:      description,
				DeploymentMethod: deployMethod,
				WorkloadType:     workloadType,
				ContainerImage:   containerImage,
				GitURL:           gitURL,
				CreateHTTPRoute:  createRoute,
				SpireEnabled:     spire,
				EnvVars:          allEnv,
			}

			resp, err := ctx.Client.CreateTool(req)
			if err != nil {
				return fmt.Errorf("creating tool: %w", err)
			}
			if !resp.Success {
				return fmt.Errorf("tool creation failed: %s", resp.Message)
			}
			fmt.Printf("Tool '%s' created in %s\n", resp.Name, resp.Namespace)
			return nil
		},
	}

	cmd.Flags().StringVar(&name, "name", "", "Tool name (required)")
	cmd.Flags().StringVar(&description, "description", "", "Tool description")
	cmd.Flags().StringVar(&protocol, "protocol", "streamable_http", "Protocol (streamable_http, sse, stdio)")
	cmd.Flags().StringVar(&deployMethod, "deploy-method", "image", "Deployment method (image, source)")
	cmd.Flags().StringVar(&containerImage, "container-image", "", "Container image")
	cmd.Flags().StringVar(&gitURL, "git-url", "", "Git repository URL")
	cmd.Flags().StringVar(&workloadType, "workload-type", "deployment", "Workload type (deployment, statefulset)")
	cmd.Flags().BoolVar(&createRoute, "create-route", false, "Create HTTP route")
	cmd.Flags().BoolVar(&spire, "spire", false, "Enable SPIRE identity")
	cmd.Flags().StringVar(&logLevel, "log-level", "", "Log level")
	cmd.Flags().StringArrayVar(&envVars, "env", nil, "Extra env var KEY=VALUE (repeatable)")
	_ = cmd.MarkFlagRequired("name")

	return cmd
}
