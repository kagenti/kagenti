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
		v.buildForm()
		return v, v.form.Init()

	case agentDeployedMsg:
		v.deploying = false
		v.result = msg.result
		v.err = msg.err
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
	}

	fv := v.vals

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
	).WithWidth(v.width - 4)
}

func (v *DeployAgentView) deploy() tea.Cmd {
	client := v.client
	fv := v.vals
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
	}

	return b.String()
}
