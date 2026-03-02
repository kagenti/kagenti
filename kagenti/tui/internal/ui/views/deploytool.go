package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/huh"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// toolFormValues holds form field values on the heap so huh's
// Value() pointers survive Bubble Tea's value-receiver copies.
type toolFormValues struct {
	name           string
	namespace      string
	framework      string
	protocol       string
	description    string
	deployMethod   string
	containerImage string
	gitURL         string
	gitRevision    string
	workloadType   string
	createRoute    bool
	spireEnabled   bool
}

// DeployToolView handles the tool deploy form.
type DeployToolView struct {
	client     *api.Client
	width      int
	height     int
	form       *huh.Form
	submitted  bool
	deploying  bool
	result     *api.CreateToolResponse
	err        error
	namespaces []string
	vals       *toolFormValues
}

// NewDeployToolView creates a new deploy tool view.
func NewDeployToolView(client *api.Client) DeployToolView {
	return DeployToolView{client: client}
}

// SetSize sets the view dimensions.
func (v *DeployToolView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

type toolDeployedMsg struct {
	result *api.CreateToolResponse
	err    error
}

// Init fetches namespaces for the form.
func (v DeployToolView) Init() tea.Cmd {
	client := v.client
	return func() tea.Msg {
		resp, err := client.ListNamespaces()
		if err != nil {
			return namespacesLoadedMsg{namespaces: []string{"team1", "team2"}}
		}
		return namespacesLoadedMsg{namespaces: resp.Namespaces}
	}
}

// Update handles messages.
func (v DeployToolView) Update(msg tea.Msg) (DeployToolView, tea.Cmd) {
	switch msg := msg.(type) {
	case namespacesLoadedMsg:
		v.namespaces = msg.namespaces
		if len(v.namespaces) == 0 {
			v.namespaces = []string{"team1", "team2"}
		}
		v.buildForm()
		return v, v.form.Init()

	case toolDeployedMsg:
		v.deploying = false
		v.result = msg.result
		v.err = msg.err
		// Navigate to tool detail on success
		if msg.err == nil && msg.result != nil && msg.result.Success {
			name := msg.result.Name
			return v, func() tea.Msg {
				return NavigateMsg{Target: "tool-detail", Name: name}
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

		if v.form != nil && msg.Type == tea.KeyEsc {
			return v, func() tea.Msg {
				return NavigateMsg{Target: "home"}
			}
		}
	}

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

func (v *DeployToolView) buildForm() {
	nsOptions := make([]huh.Option[string], len(v.namespaces))
	for i, ns := range v.namespaces {
		nsOptions[i] = huh.NewOption(ns, ns)
	}

	// Heap-allocate form values so huh's Value() pointers
	// survive Bubble Tea's value-receiver struct copies.
	v.vals = &toolFormValues{
		namespace:    v.client.Namespace,
		framework:    "Python",
		protocol:     "streamable_http",
		deployMethod: "image",
		workloadType: "deployment",
		gitRevision:  "main",
	}

	fv := v.vals

	v.form = huh.NewForm(
		huh.NewGroup(
			huh.NewInput().
				Title("Tool Name").
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
			huh.NewInput().
				Title("Description").
				Value(&fv.description),
			huh.NewSelect[string]().
				Title("Protocol").
				Options(
					huh.NewOption("Streamable HTTP", "streamable_http"),
					huh.NewOption("SSE", "sse"),
					huh.NewOption("stdio", "stdio"),
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
			huh.NewSelect[string]().
				Title("Workload Type").
				Options(
					huh.NewOption("Deployment", "deployment"),
					huh.NewOption("StatefulSet", "statefulset"),
				).
				Value(&fv.workloadType),
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

func (v *DeployToolView) deploy() tea.Cmd {
	client := v.client
	fv := v.vals
	req := &api.CreateToolRequest{
		Name:             fv.name,
		Namespace:        fv.namespace,
		Protocol:         fv.protocol,
		Framework:        fv.framework,
		Description:      fv.description,
		DeploymentMethod: fv.deployMethod,
		WorkloadType:     fv.workloadType,
		ContainerImage:   fv.containerImage,
		GitURL:           fv.gitURL,
		GitRevision:      fv.gitRevision,
		CreateHTTPRoute:  fv.createRoute,
		SpireEnabled:     fv.spireEnabled,
	}
	return func() tea.Msg {
		resp, err := client.CreateTool(req)
		if err != nil {
			return toolDeployedMsg{err: err}
		}
		return toolDeployedMsg{result: resp}
	}
}

// View renders the deploy tool view.
func (v DeployToolView) View() string {
	var b strings.Builder
	b.WriteString(theme.TitleStyle.Render("Deploy Tool") + "\n\n")

	if v.deploying {
		b.WriteString(theme.WarningStyle.Render("  Deploying...") + "\n")
		return b.String()
	}

	if v.result != nil {
		if v.result.Success {
			b.WriteString(theme.SuccessStyle.Render(fmt.Sprintf("  ✓ Tool '%s' created in %s", v.result.Name, v.result.Namespace)) + "\n")
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
