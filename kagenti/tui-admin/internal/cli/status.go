package cli

import (
	"context"
	"fmt"
	"os"
	"text/tabwriter"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui-admin/internal/config"
)

// Component maps component names to K8s deployment details.
type Component struct {
	Name       string
	Namespace  string
	Label      string // label selector
	Deployment string // deployment name (if different from label)
}

// KnownComponents returns the list of kagenti platform components.
func KnownComponents() []Component {
	return []Component{
		{Name: "ui", Namespace: "kagenti-system", Label: "app.kubernetes.io/name=kagenti-ui", Deployment: "kagenti-ui"},
		{Name: "backend", Namespace: "kagenti-system", Label: "app.kubernetes.io/name=kagenti-backend", Deployment: "kagenti-backend"},
		{Name: "operator", Namespace: "kagenti-system", Label: "control-plane=controller-manager"},
		{Name: "webhook", Namespace: "kagenti-webhook-system", Label: "app.kubernetes.io/name=kagenti-webhook"},
		{Name: "keycloak", Namespace: "keycloak", Label: "app=keycloak"},
		{Name: "phoenix", Namespace: "kagenti-system", Label: "app=phoenix"},
		{Name: "kiali", Namespace: "istio-system", Label: "app=kiali"},
		{Name: "weather-tool", Namespace: "team1", Label: "app.kubernetes.io/name=weather-tool"},
		{Name: "weather-service", Namespace: "team1", Label: "app.kubernetes.io/name=weather-service"},
	}
}

// FindComponent looks up a component by name.
func FindComponent(name string) (*Component, error) {
	for _, c := range KnownComponents() {
		if c.Name == name {
			return &c, nil
		}
	}
	return nil, fmt.Errorf("unknown component: %s (valid: ui, backend, operator, webhook, keycloak, phoenix, kiali, weather-tool, weather-service)", name)
}

func newStatusCmd(ctx *AdminContext) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status [component]",
		Short: "Show platform status, component details, or last test results",
		Long: `Show status of the kagenti platform or a specific component.

Without arguments, shows a dashboard of all components.
With a component name, shows detailed status for that component.
Use 'status last-test' to show the last test run results.
Use 'status deps' to show dependency versions and overrides.
Use 'status images' to show all running images.`,
		Example: `  kagenti-admin status              # Dashboard
  kagenti-admin status ui           # UI component details
  kagenti-admin status backend      # Backend details
  kagenti-admin status last-test    # Last test results
  kagenti-admin status deps         # Dependency versions
  kagenti-admin status images       # Running images`,
		Args: cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				return showDashboard(ctx, cmd)
			}

			switch args[0] {
			case "last-test":
				return showLastTest(cmd)
			case "deps":
				return showDeps(ctx, cmd)
			case "images":
				return showImages(ctx, cmd)
			default:
				return showComponent(ctx, cmd, args[0])
			}
		},
	}

	return cmd
}

func showDashboard(ctx *AdminContext, cmd *cobra.Command) error {
	fmt.Fprintln(cmd.OutOrStdout(), "Kagenti Platform Status")
	fmt.Fprintln(cmd.OutOrStdout())

	// Cluster info
	platform, _ := ctx.ClusterManager.Detect(context.Background())
	fmt.Fprintf(cmd.OutOrStdout(), "Platform: %s\n\n", platform)

	// Component status table
	w := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
	fmt.Fprintln(w, "COMPONENT\tNAMESPACE\tSTATUS\tREADY")

	r := ctx.getRunner()
	for _, comp := range KnownComponents() {
		result, err := r.RunSilent(context.Background(), "kubectl", "get", "pods",
			"-n", comp.Namespace, "-l", comp.Label, "--no-headers",
			"-o", "custom-columns=STATUS:.status.phase,READY:.status.containerStatuses[0].ready")
		status := "Not Found"
		ready := "-"
		if err == nil && result.Stdout != "" {
			lines := splitLines(result.Stdout)
			if len(lines) > 0 {
				parts := splitFields(lines[0])
				if len(parts) >= 1 {
					status = parts[0]
				}
				if len(parts) >= 2 {
					ready = parts[1]
				}
			}
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", comp.Name, comp.Namespace, status, ready)
	}
	w.Flush()
	return nil
}

func showComponent(ctx *AdminContext, cmd *cobra.Command, name string) error {
	comp, err := FindComponent(name)
	if err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Component: %s\n", comp.Name)
	fmt.Fprintf(cmd.OutOrStdout(), "Namespace: %s\n\n", comp.Namespace)

	r := ctx.getRunner()

	// Pod details
	result, err := r.RunSilent(context.Background(), "kubectl", "get", "pods",
		"-n", comp.Namespace, "-l", comp.Label, "-o", "wide", "--no-headers")
	if err == nil && result.Stdout != "" {
		fmt.Fprintln(cmd.OutOrStdout(), "Pods:")
		fmt.Fprintln(cmd.OutOrStdout(), result.Stdout)
	} else {
		fmt.Fprintln(cmd.OutOrStdout(), "No pods found")
	}

	// Image info
	result, err = r.RunSilent(context.Background(), "kubectl", "get", "pods",
		"-n", comp.Namespace, "-l", comp.Label,
		"-o", "jsonpath={.items[0].spec.containers[*].image}")
	if err == nil && result.Stdout != "" {
		fmt.Fprintf(cmd.OutOrStdout(), "\nImages: %s\n", result.Stdout)
	}

	return nil
}

func showLastTest(cmd *cobra.Command) error {
	cfg := config.Load()
	if cfg.LastTest == nil {
		fmt.Fprintln(cmd.OutOrStdout(), "No test results saved. Run: kagenti-admin test")
		return nil
	}

	t := cfg.LastTest
	result := "PASSED"
	if !t.Passed {
		result = "FAILED"
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Last Test: %s\n", result)
	fmt.Fprintf(cmd.OutOrStdout(), "Platform:  %s\n", t.Platform)
	fmt.Fprintf(cmd.OutOrStdout(), "Time:      %s\n", t.Timestamp)

	if len(t.Deps) > 0 {
		fmt.Fprintln(cmd.OutOrStdout(), "\nDependency Overrides:")
		w := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
		fmt.Fprintln(w, "REPO\tREF\tCOMMIT")
		for _, d := range t.Deps {
			fmt.Fprintf(w, "%s\t%s\t%s\n", d.Repo, d.Ref, d.Commit)
		}
		w.Flush()
	}

	return nil
}

func showDeps(ctx *AdminContext, cmd *cobra.Command) error {
	r := ctx.getRunner()

	fmt.Fprintln(cmd.OutOrStdout(), "Dependency Versions:")
	fmt.Fprintln(cmd.OutOrStdout())

	w := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
	fmt.Fprintln(w, "COMPONENT\tIMAGE\tSOURCE")

	// Check key deployments for their image versions
	checks := []struct {
		name      string
		namespace string
		deploy    string
	}{
		{"kagenti-ui", "kagenti-system", "kagenti-ui"},
		{"kagenti-backend", "kagenti-system", "kagenti-backend"},
		{"kagenti-webhook", "kagenti-webhook-system", "kagenti-webhook"},
		{"kagenti-operator", "kagenti-system", "kagenti-controller-manager"},
	}

	overrides := os.Getenv("KAGENTI_DEP_BUILDS")

	for _, c := range checks {
		result, err := r.RunSilent(context.Background(), "kubectl", "get", "deployment",
			"-n", c.namespace, c.deploy,
			"-o", "jsonpath={.spec.template.spec.containers[0].image}")
		image := "not deployed"
		source := "chart"
		if err == nil && result.Stdout != "" {
			image = result.Stdout
			if contains(image, ":local") || contains(image, ":latest") {
				if overrides != "" && contains(overrides, c.name) {
					source = "OVERRIDE"
				} else {
					source = "local"
				}
			}
		}
		fmt.Fprintf(w, "%s\t%s\t%s\n", c.name, image, source)
	}
	w.Flush()

	if overrides != "" {
		fmt.Fprintf(cmd.OutOrStdout(), "\nActive overrides: %s\n", overrides)
	}

	return nil
}

func showImages(ctx *AdminContext, cmd *cobra.Command) error {
	r := ctx.getRunner()

	fmt.Fprintln(cmd.OutOrStdout(), "Running Images:")
	fmt.Fprintln(cmd.OutOrStdout())

	result, err := r.RunSilent(context.Background(), "kubectl", "get", "pods", "-A",
		"-o", "jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name}: {range .spec.containers[*]}{.image} {end}{\"\n\"}{end}")
	if err != nil {
		return fmt.Errorf("get pod images: %w", err)
	}

	fmt.Fprintln(cmd.OutOrStdout(), result.Stdout)
	return nil
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 ||
		(len(s) > 0 && len(substr) > 0 && findSubstring(s, substr)))
}

func findSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

func splitLines(s string) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			line := s[start:i]
			if len(line) > 0 {
				lines = append(lines, line)
			}
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}

func splitFields(s string) []string {
	var fields []string
	inField := false
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == ' ' || s[i] == '\t' {
			if inField {
				fields = append(fields, s[start:i])
				inField = false
			}
		} else {
			if !inField {
				start = i
				inField = true
			}
		}
	}
	if inField {
		fields = append(fields, s[start:])
	}
	return fields
}
