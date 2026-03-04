package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/huh"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// agentFormValues holds form field values on the heap so huh's
// Value() pointers survive Bubble Tea's value-receiver copies.
type agentFormValues struct {
	name           string
	namespace      string
	framework      string
	protocol       string
	deployMethod   string
	containerImage string
	gitURL         string
	gitBranch      string
	createRoute    bool
	spireEnabled   bool
	llmEnv   string
	llmModel string
	logLevel string
	mcpTool        string
	mcpURLOverride string
	extraEnvVars   string
}

// DeployAgentView handles the agent deploy form.
type DeployAgentView struct {
	client     *api.Client
	width      int
	height     int
	form       *huh.Form
	submitted  bool
	deploying  bool
	result     *api.CreateAgentResponse
	err        error
	namespaces []string
	tools      []api.ToolSummary
	vals       *agentFormValues
}

// NewDeployAgentView creates a new deploy agent view.
func NewDeployAgentView(client *api.Client) DeployAgentView {
	return DeployAgentView{client: client}
}

// SetSize sets the view dimensions.
func (v *DeployAgentView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type namespacesLoadedMsg struct {
	namespaces []string
	err        error
}

type agentDeployedMsg struct {
	result *api.CreateAgentResponse
	err    error
}

type toolsForAgentMsg struct {
	tools []api.ToolSummary
}

// Init fetches namespaces for the form.
func (v DeployAgentView) Init() tea.Cmd {
	client := v.client
	return func() tea.Msg {
		resp, err := client.ListNamespaces()
		if err != nil {
			return namespacesLoadedMsg{namespaces: []string{"team1", "team2"}, err: nil}
		}
		return namespacesLoadedMsg{namespaces: resp.Namespaces}
	}
}

// Update handles messages.
func (v DeployAgentView) Update(msg tea.Msg) (DeployAgentView, tea.Cmd) {
	switch msg := msg.(type) {
	case namespacesLoadedMsg:
		v.namespaces = msg.namespaces
		if len(v.namespaces) == 0 {
			v.namespaces = []string{"team1", "team2"}
		}
		// Fetch available tools before building the form
		client := v.client
		return v, func() tea.Msg {
			resp, err := client.ListTools("")
			if err != nil {
				return toolsForAgentMsg{}
			}
			return toolsForAgentMsg{tools: resp.Items}
		}

	case toolsForAgentMsg:
		v.tools = msg.tools
		v.buildForm()
		return v, v.form.Init()

	case agentDeployedMsg:
		v.deploying = false
		v.result = msg.result
		v.err = msg.err
		// Navigate to agent detail on success
		if msg.err == nil && msg.result != nil && msg.result.Success {
			name := msg.result.Name
			return v, func() tea.Msg {
				return NavigateMsg{Target: "agent-detail", Name: name}
			}
		}
		return v, nil

	case tea.KeyMsg:
		if v.submitted || v.deploying {
			if msg.Type == tea.KeyEsc {
				return v, func() tea.Msg {
					return NavigateMsg{Target: "home"}
				}
			}
			return v, nil
		}

		if v.form != nil {
			if msg.Type == tea.KeyEsc {
				return v, func() tea.Msg {
					return NavigateMsg{Target: "home"}
				}
			}
		}
	}

	// Delegate to huh form
	if v.form != nil && !v.submitted {
		form, cmd := v.form.Update(msg)
		if f, ok := form.(*huh.Form); ok {
			v.form = f
		}

		if v.form.State == huh.StateCompleted {
			v.submitted = true
			v.deploying = true
			return v, tea.Batch(cmd, v.deploy())
		}
		return v, cmd
	}

	return v, nil
}

// mcpToolURL generates the in-cluster service URL for an MCP tool.
func mcpToolURL(tool api.ToolSummary) string {
	path := "/mcp"
	switch tool.Labels.Protocol {
	case "sse":
		path = "/sse"
	}
	return fmt.Sprintf("http://%s-mcp.%s.svc.cluster.local:8000%s",
		tool.Name, tool.Namespace, path)
}

func (v *DeployAgentView) buildForm() {
	nsOptions := make([]huh.Option[string], len(v.namespaces))
	for i, ns := range v.namespaces {
		nsOptions[i] = huh.NewOption(ns, ns)
	}

	// Heap-allocate form values so huh's Value() pointers
	// survive Bubble Tea's value-receiver struct copies.
	v.vals = &agentFormValues{
		namespace:    v.client.Namespace,
		framework:    "LangGraph",
		protocol:     "a2a",
		deployMethod: "image",
		gitBranch:    "main",
		llmEnv:       "openai",
		logLevel:     "INFO",
	}

	fv := v.vals

	// Build tool select options
	toolOptions := []huh.Option[string]{huh.NewOption("None", "")}
	for _, t := range v.tools {
		label := t.Name
		if t.Namespace != "" {
			label += " (" + t.Namespace + ")"
		}
		toolOptions = append(toolOptions, huh.NewOption(label, t.Name))
	}

	v.form = huh.NewForm(
		huh.NewGroup(
			huh.NewInput().
				Title("Agent Name").
				Value(&fv.name).
				Validate(func(s string) error {
					if s == "" {
						return fmt.Errorf("name is required")
					}
					return nil
				}),
			huh.NewSelect[string]().
				Title("Namespace").
				Options(nsOptions...).
				Value(&fv.namespace),
			huh.NewSelect[string]().
				Title("Framework").
				Options(
					huh.NewOption("LangGraph", "LangGraph"),
					huh.NewOption("CrewAI", "CrewAI"),
					huh.NewOption("AG2", "AG2"),
					huh.NewOption("Custom", "Custom"),
				).
				Value(&fv.framework),
			huh.NewSelect[string]().
				Title("Protocol").
				Options(
					huh.NewOption("A2A", "a2a"),
					huh.NewOption("MCP", "mcp"),
				).
				Value(&fv.protocol),
		).Title("Basics"),

		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Deployment Method").
				Options(
					huh.NewOption("Container Image", "image"),
					huh.NewOption("Git Source", "source"),
				).
				Value(&fv.deployMethod),
			huh.NewInput().
				Title("Container Image").
				Description("e.g. quay.io/org/image:tag").
				Value(&fv.containerImage).
				Validate(func(s string) error {
					if fv.deployMethod == "image" && s == "" {
						return fmt.Errorf("container image is required for image deployment")
					}
					return nil
				}),
			huh.NewInput().
				Title("Git URL").
				Description("e.g. https://github.com/org/repo").
				Value(&fv.gitURL).
				Validate(func(s string) error {
					if fv.deployMethod == "source" && s == "" {
						return fmt.Errorf("git URL is required for source deployment")
					}
					return nil
				}),
			huh.NewInput().
				Title("Git Branch").
				Value(&fv.gitBranch),
		).Title("Source"),

		huh.NewGroup(
			huh.NewConfirm().
				Title("Create HTTP Route?").
				Value(&fv.createRoute),
			huh.NewConfirm().
				Title("Enable SPIRE Identity?").
				Value(&fv.spireEnabled),
		).Title("Networking"),

		huh.NewGroup(
			huh.NewSelect[string]().
				Title("LLM Environment").
				Description("Injects env vars from the 'environments' ConfigMap in the namespace").
				Options(
					huh.NewOption("OpenAI (from openai-secret)", "openai"),
					huh.NewOption("Ollama (local)", "ollama"),
					huh.NewOption("None", ""),
				).
				Value(&fv.llmEnv),
			huh.NewInput().
				Title("Model Override").
				Description("Leave empty to use preset default").
				Value(&fv.llmModel),
			huh.NewInput().
				Title("Log Level").
				Description("Agent log level").
				Value(&fv.logLevel),
			huh.NewSelect[string]().
				Title("Connect to MCP Tool").
				Description("Auto-generates MCP_URL from tool's in-cluster service").
				Options(toolOptions...).
				Value(&fv.mcpTool),
			huh.NewInput().
				Title("MCP URL Override").
				Description("Leave empty to auto-generate, or enter a custom URL").
				Value(&fv.mcpURLOverride),
			huh.NewInput().
				Title("Extra Env Vars").
				Description("KEY=VALUE pairs, comma-separated (optional)").
				Value(&fv.extraEnvVars),
		).Title("Environment"),
	).WithWidth(v.width - 4)
}

// llmPresetEnvVars returns env vars for a given LLM environment preset.
// These match the "environments" ConfigMap entries deployed by the Helm chart.
func llmPresetEnvVars(preset, modelOverride string) []api.EnvVar {
	secretRef := func(secretName, key string) *api.EnvVarSource {
		return &api.EnvVarSource{
			SecretKeyRef: &api.SecretKeyRef{Name: secretName, Key: key},
		}
	}

	switch preset {
	case "openai":
		model := "gpt-4o-mini-2024-07-18"
		if modelOverride != "" {
			model = modelOverride
		}
		return []api.EnvVar{
			{Name: "OPENAI_API_KEY", ValueFrom: secretRef("openai-secret", "apikey")},
			{Name: "LLM_API_KEY", ValueFrom: secretRef("openai-secret", "apikey")},
			{Name: "LLM_API_BASE", Value: "https://api.openai.com/v1"},
			{Name: "LLM_MODEL", Value: model},
		}
	case "ollama":
		model := "llama3.2:3b-instruct-fp16"
		if modelOverride != "" {
			model = modelOverride
		}
		return []api.EnvVar{
			{Name: "LLM_API_BASE", Value: "http://host.docker.internal:11434/v1"},
			{Name: "LLM_API_KEY", Value: "dummy"},
			{Name: "LLM_MODEL", Value: model},
		}
	default:
		return nil
	}
}

// parseExtraEnvVars parses comma-separated KEY=VALUE pairs into env vars.
func parseExtraEnvVars(raw string) []api.EnvVar {
	if raw == "" {
		return nil
	}
	var envVars []api.EnvVar
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		parts := strings.SplitN(pair, "=", 2)
		if len(parts) == 2 {
			envVars = append(envVars, api.EnvVar{
				Name:  strings.TrimSpace(parts[0]),
				Value: strings.TrimSpace(parts[1]),
			})
		}
	}
	return envVars
}

func (v *DeployAgentView) deploy() tea.Cmd {
	client := v.client
	fv := v.vals

	// Resolve MCP_URL: explicit override wins, otherwise generate from selected tool
	mcpURL := fv.mcpURLOverride
	if mcpURL == "" && fv.mcpTool != "" {
		for _, t := range v.tools {
			if t.Name == fv.mcpTool {
				mcpURL = mcpToolURL(t)
				break
			}
		}
	}

	envVars := llmPresetEnvVars(fv.llmEnv, fv.llmModel)
	if mcpURL != "" {
		envVars = append(envVars, api.EnvVar{Name: "MCP_URL", Value: mcpURL})
	}
	if fv.logLevel != "" {
		envVars = append(envVars, api.EnvVar{Name: "LOG_LEVEL", Value: fv.logLevel})
	}
	envVars = append(envVars, parseExtraEnvVars(fv.extraEnvVars)...)

	req := &api.CreateAgentRequest{
		Name:              fv.name,
		Namespace:         fv.namespace,
		Protocol:          fv.protocol,
		Framework:         fv.framework,
		DeploymentMethod:  fv.deployMethod,
		WorkloadType:      "deployment",
		ContainerImage:    fv.containerImage,
		GitURL:            fv.gitURL,
		GitBranch:         fv.gitBranch,
		CreateHTTPRoute:   fv.createRoute,
		AuthBridgeEnabled: true,
		SpireEnabled:      fv.spireEnabled,
		EnvVars:           envVars,
	}
	return func() tea.Msg {
		resp, err := client.CreateAgent(req)
		if err != nil {
			return agentDeployedMsg{err: err}
		}
		return agentDeployedMsg{result: resp}
	}
}

// View renders the deploy agent view.
func (v DeployAgentView) View() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Deploy Agent") + "\n\n")

	if v.deploying {
		b.WriteString(theme.WarningStyle.Render("  Deploying...") + "\n")
		return b.String()
	}

	if v.result != nil {
		if v.result.Success {
			b.WriteString(theme.SuccessStyle.Render(fmt.Sprintf("  ✓ Agent '%s' created in %s", v.result.Name, v.result.Namespace)) + "\n")
		} else {
			b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  ✗ %s", v.result.Message)) + "\n")
		}
		b.WriteString("\n" + theme.MutedStyle.Render("  Esc back"))
		return b.String()
	}

	if v.err != nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Error: %s", v.err.Error())) + "\n")
		b.WriteString("\n" + theme.MutedStyle.Render("  Esc back"))
		return b.String()
	}

	if v.form != nil && !v.submitted {
		b.WriteString(v.form.View())

		// Live preview of the MCP_URL that will be injected
		if v.vals != nil {
			var previewURL string
			if v.vals.mcpURLOverride != "" {
				previewURL = v.vals.mcpURLOverride
			} else if v.vals.mcpTool != "" {
				for _, t := range v.tools {
					if t.Name == v.vals.mcpTool {
						previewURL = mcpToolURL(t)
						break
					}
				}
			}
			if previewURL != "" {
				b.WriteString("\n" + theme.LabelStyle.Render("  MCP_URL → ") + theme.MutedStyle.Render(previewURL))
			}
		}
	}

	return b.String()
}
