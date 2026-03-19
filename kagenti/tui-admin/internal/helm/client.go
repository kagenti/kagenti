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

// Client wraps the Helm SDK for chart operations.
type Client struct {
	Settings   *cli.EnvSettings
	Stdout     io.Writer
	Kubeconfig string
}

// NewClient creates a Helm client. If kubeconfig is empty, uses default.
func NewClient(kubeconfig string) *Client {
	settings := cli.New()
	if kubeconfig != "" {
		settings.KubeConfig = kubeconfig
	}
	return &Client{
		Settings:   settings,
		Stdout:     os.Stdout,
		Kubeconfig: kubeconfig,
	}
}

// actionConfig creates a Helm action.Configuration for a namespace.
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

	// Check if release exists
	hist := action.NewHistory(cfg)
	hist.Max = 1
	_, err = hist.Run(name)
	if err == nil {
		// Release exists — upgrade
		return c.upgrade(cfg, name, chartPath, namespace, values)
	}

	// Release doesn't exist — install
	return c.install(cfg, name, chartPath, namespace, values)
}

func (c *Client) install(cfg *action.Configuration, name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	install := action.NewInstall(cfg)
	install.ReleaseName = name
	install.Namespace = namespace
	install.CreateNamespace = true
	install.Wait = true
	install.Timeout = 5 * time.Minute

	chart, err := loader.Load(chartPath)
	if err != nil {
		return nil, fmt.Errorf("load chart %s: %w", chartPath, err)
	}

	fmt.Fprintf(c.Stdout, "Installing %s in %s...\n", name, namespace)
	rel, err := install.Run(chart, values)
	if err != nil {
		return nil, fmt.Errorf("helm install %s: %w", name, err)
	}

	fmt.Fprintf(c.Stdout, "Installed %s (status: %s)\n", name, rel.Info.Status)
	return rel, nil
}

func (c *Client) upgrade(cfg *action.Configuration, name, chartPath, namespace string, values map[string]interface{}) (*release.Release, error) {
	upgrade := action.NewUpgrade(cfg)
	upgrade.Namespace = namespace
	upgrade.Wait = true
	upgrade.Timeout = 5 * time.Minute

	chart, err := loader.Load(chartPath)
	if err != nil {
		return nil, fmt.Errorf("load chart %s: %w", chartPath, err)
	}

	fmt.Fprintf(c.Stdout, "Upgrading %s in %s...\n", name, namespace)
	rel, err := upgrade.Run(name, chart, values)
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

	uninstall := action.NewUninstall(cfg)
	fmt.Fprintf(c.Stdout, "Uninstalling %s from %s...\n", name, namespace)
	_, err = uninstall.Run(name)
	if err != nil {
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

	list := action.NewList(cfg)
	list.AllNamespaces = namespace == ""
	return list.Run()
}
