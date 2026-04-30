// Package helm provides native Helm SDK operations, replacing shell-out to helm CLI.
package helm

import (
	"fmt"
	"io"
	"os"
	"time"

	"helm.sh/helm/v3/pkg/action"
	"helm.sh/helm/v3/pkg/chart/loader"
	"helm.sh/helm/v3/pkg/cli"
	"helm.sh/helm/v3/pkg/release"
)

// Interface defines operations for Helm chart management.
type Interface interface {
	InstallOrUpgrade(name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error)
	Uninstall(name, namespace string) error
	List(namespace string) ([]*release.Release, error)
}

// Client wraps the Helm SDK for chart operations. Implements Interface.
type Client struct {
	Settings   *cli.EnvSettings
	Stdout     io.Writer
	Kubeconfig string
}

// Ensure Client implements Interface.
var _ Interface = (*Client)(nil)

// NewClient creates a Helm client.
func NewClient(kubeconfig string) *Client {
	settings := cli.New()
	if kubeconfig != "" {
		settings.KubeConfig = kubeconfig
	}
	return &Client{Settings: settings, Stdout: os.Stdout, Kubeconfig: kubeconfig}
}

func (c *Client) actionConfig(namespace string) (*action.Configuration, error) {
	cfg := new(action.Configuration)
	if err := cfg.Init(c.Settings.RESTClientGetter(), namespace, "secret", func(format string, v ...interface{}) {
		fmt.Fprintf(c.Stdout, format+"\n", v...)
	}); err != nil {
		return nil, fmt.Errorf("helm config init: %w", err)
	}
	return cfg, nil
}

// InstallOrUpgrade installs or upgrades a Helm chart.
func (c *Client) InstallOrUpgrade(name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	cfg, err := c.actionConfig(namespace)
	if err != nil {
		return nil, err
	}

	hist := action.NewHistory(cfg)
	hist.Max = 1
	if _, err = hist.Run(name); err == nil {
		return c.upgrade(cfg, name, chartPath, namespace, values)
	}
	return c.install(cfg, name, chartPath, namespace, values)
}

func (c *Client) install(cfg *action.Configuration, name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	i := action.NewInstall(cfg)
	i.ReleaseName = name
	i.Namespace = namespace
	i.CreateNamespace = true
	i.Wait = true
	i.Timeout = 5 * time.Minute

	chart, err := loader.Load(chartPath)
	if err != nil {
		return nil, fmt.Errorf("load chart %s: %w", chartPath, err)
	}

	fmt.Fprintf(c.Stdout, "Installing %s in %s...\n", name, namespace)
	rel, err := i.Run(chart, values)
	if err != nil {
		return nil, fmt.Errorf("helm install %s: %w", name, err)
	}

	fmt.Fprintf(c.Stdout, "Installed %s (status: %s)\n", name, rel.Info.Status)
	return rel, nil
}

func (c *Client) upgrade(cfg *action.Configuration, name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	u := action.NewUpgrade(cfg)
	u.Namespace = namespace
	u.Wait = true
	u.Timeout = 5 * time.Minute

	chart, err := loader.Load(chartPath)
	if err != nil {
		return nil, fmt.Errorf("load chart %s: %w", chartPath, err)
	}

	fmt.Fprintf(c.Stdout, "Upgrading %s in %s...\n", name, namespace)
	rel, err := u.Run(name, chart, values)
	if err != nil {
		return nil, fmt.Errorf("helm upgrade %s: %w", name, err)
	}

	fmt.Fprintf(c.Stdout, "Upgraded %s (status: %s)\n", name, rel.Info.Status)
	return rel, nil
}

// Uninstall removes a Helm release.
func (c *Client) Uninstall(name, namespace string) error {
	cfg, err := c.actionConfig(namespace)
	if err != nil {
		return err
	}

	fmt.Fprintf(c.Stdout, "Uninstalling %s from %s...\n", name, namespace)
	if _, err = action.NewUninstall(cfg).Run(name); err != nil {
		return fmt.Errorf("helm uninstall %s: %w", name, err)
	}

	fmt.Fprintf(c.Stdout, "Uninstalled %s\n", name)
	return nil
}

// List returns all releases in a namespace.
func (c *Client) List(namespace string) ([]*release.Release, error) {
	cfg, err := c.actionConfig(namespace)
	if err != nil {
		return nil, err
	}

	l := action.NewList(cfg)
	l.AllNamespaces = namespace == ""
	return l.Run()
}

// MockClient is a test double for helm.Interface.
type MockClient struct {
	InstallCalls []string
	Releases     []*release.Release
	Err          error
}

var _ Interface = (*MockClient)(nil)

func (m *MockClient) InstallOrUpgrade(name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	m.InstallCalls = append(m.InstallCalls, name)
	if m.Err != nil {
		return nil, m.Err
	}
	rel := &release.Release{Name: name, Namespace: namespace}
	return rel, nil
}

func (m *MockClient) Uninstall(name, namespace string) error {
	return m.Err
}

func (m *MockClient) List(namespace string) ([]*release.Release, error) {
	return m.Releases, m.Err
}
