package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/helpers"
)

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
		containerImage string
		gitURL         string
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
							if t.Labels.Protocol == "sse" {
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
				WorkloadType:      "deployment",
				ContainerImage:    containerImage,
				GitURL:            gitURL,
				GitBranch:         gitBranch,
				CreateHTTPRoute:   createRoute,
				AuthBridgeEnabled: true,
				SpireEnabled:      spire,
				EnvVars:           allEnv,
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
	cmd.Flags().StringVar(&containerImage, "container-image", "", "Container image")
	cmd.Flags().StringVar(&gitURL, "git-url", "", "Git repository URL")
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
