package runner

import (
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
)

// PreflightCheck represents a single dependency check.
type PreflightCheck struct {
	Name     string
	Command  string // binary name to check
	Required bool   // false = warning only
	Hint     string // install instructions
}

// PreflightResult holds the outcome of a check.
type PreflightResult struct {
	Check PreflightCheck
	Found bool
	Path  string // resolved path if found
}

// PlatformPreflightChecks returns the required dependencies for a platform.
func PlatformPreflightChecks(platform string) []PreflightCheck {
	common := []PreflightCheck{
		{Name: "kubectl", Command: "kubectl", Required: true, Hint: "https://kubernetes.io/docs/tasks/tools/"},
		{Name: "helm", Command: "helm", Required: true, Hint: "brew install helm@3 (v3 required)"},
		{Name: "python3", Command: "python3", Required: true, Hint: "brew install python3"},
		{Name: "uv", Command: "uv", Required: true, Hint: "https://docs.astral.sh/uv/"},
		{Name: "jq", Command: "jq", Required: true, Hint: "brew install jq"},
	}

	switch platform {
	case "kind":
		common = append(common,
			PreflightCheck{Name: "kind", Command: "kind", Required: true, Hint: "https://kind.sigs.k8s.io/"},
			PreflightCheck{Name: "docker", Command: "docker", Required: true, Hint: "Install Docker Desktop or Rancher Desktop"},
		)
	case "k3s", "rancher-desktop":
		common = append(common,
			PreflightCheck{Name: "rdctl", Command: "rdctl", Required: true, Hint: "Install Rancher Desktop from https://rancherdesktop.io/"},
		)
	case "hypershift":
		common = append(common,
			PreflightCheck{Name: "oc", Command: "oc", Required: true, Hint: "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/"},
			PreflightCheck{Name: "aws", Command: "aws", Required: true, Hint: "https://aws.amazon.com/cli/"},
			PreflightCheck{Name: "hcp", Command: "hcp", Required: false, Hint: "Install via hypershift:setup skill"},
		)
	}

	common = append(common,
		PreflightCheck{Name: "ollama", Command: "ollama", Required: false, Hint: "https://ollama.com/ (optional, for local LLM)"},
		PreflightCheck{Name: "go", Command: "go", Required: false, Hint: "brew install go (for kagenti-admin development)"},
	)

	return common
}

// RunPreflightChecks validates all required dependencies are available.
func RunPreflightChecks(w io.Writer, platform string) (passed bool, results []PreflightResult) {
	checks := PlatformPreflightChecks(platform)
	passed = true

	fmt.Fprintf(w, "Preflight checks (%s on %s/%s):\n", platform, runtime.GOOS, runtime.GOARCH)

	for _, check := range checks {
		found := CommandExists(check.Command)
		result := PreflightResult{Check: check, Found: found}

		if found {
			// Try to get path
			if p, err := findPath(check.Command); err == nil {
				result.Path = p
			}
			fmt.Fprintf(w, "  ✓ %-12s  %s\n", check.Name, result.Path)
		} else if check.Required {
			fmt.Fprintf(w, "  ✗ %-12s  MISSING (required) — %s\n", check.Name, check.Hint)
			passed = false
		} else {
			fmt.Fprintf(w, "  - %-12s  not found (optional) — %s\n", check.Name, check.Hint)
		}

		results = append(results, result)
	}

	fmt.Fprintln(w)
	if passed {
		fmt.Fprintln(w, "All required dependencies found.")
	} else {
		fmt.Fprintln(w, "Some required dependencies are missing. Install them and retry.")
	}

	return passed, results
}

// DetectOS returns the current OS and architecture.
func DetectOS() (os string, arch string) {
	return runtime.GOOS, runtime.GOARCH
}

func findPath(name string) (string, error) {
	// Check common macOS paths
	paths := []string{
		"/opt/homebrew/bin/" + name,
		"/usr/local/bin/" + name,
		"/usr/bin/" + name,
	}

	// Also check PATH-resolved
	for _, dir := range strings.Split(os.Getenv("PATH"), ":") {
		p := dir + "/" + name
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}

	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	return name, fmt.Errorf("not found")
}
