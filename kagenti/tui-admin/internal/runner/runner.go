// Package runner provides shell command execution for cluster operations.
// It wraps kubectl, helm, kind, rdctl, and other CLI tools with structured
// output parsing and error handling.
package runner

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

// Runner executes shell commands for cluster operations.
type Runner struct {
	Stdout     io.Writer
	Stderr     io.Writer
	Kubeconfig string
	DryRun     bool
}

// New creates a Runner with default stdout/stderr.
func New() *Runner {
	return &Runner{
		Stdout: os.Stdout,
		Stderr: os.Stderr,
	}
}

// Result holds the output of a command execution.
type Result struct {
	Stdout   string
	Stderr   string
	ExitCode int
}

// Run executes a command and returns the result.
func (r *Runner) Run(ctx context.Context, name string, args ...string) (*Result, error) {
	if r.DryRun {
		fmt.Fprintf(r.Stdout, "[dry-run] %s %s\n", name, strings.Join(args, " "))
		return &Result{}, nil
	}

	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = io.MultiWriter(&stdout, r.Stdout)
	cmd.Stderr = io.MultiWriter(&stderr, r.Stderr)

	if r.Kubeconfig != "" {
		cmd.Env = append(os.Environ(), "KUBECONFIG="+r.Kubeconfig)
	}

	err := cmd.Run()
	result := &Result{
		Stdout: stdout.String(),
		Stderr: stderr.String(),
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		result.ExitCode = exitErr.ExitCode()
		return result, fmt.Errorf("command %q exited with code %d: %s", name, result.ExitCode, stderr.String())
	}
	return result, err
}

// RunSilent executes a command and captures output without printing.
func (r *Runner) RunSilent(ctx context.Context, name string, args ...string) (*Result, error) {
	if r.DryRun {
		return &Result{}, nil
	}

	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if r.Kubeconfig != "" {
		cmd.Env = append(os.Environ(), "KUBECONFIG="+r.Kubeconfig)
	}

	err := cmd.Run()
	result := &Result{
		Stdout: strings.TrimSpace(stdout.String()),
		Stderr: strings.TrimSpace(stderr.String()),
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		result.ExitCode = exitErr.ExitCode()
		return result, fmt.Errorf("command %q exited with code %d: %s", name, result.ExitCode, result.Stderr)
	}
	return result, err
}

// Kubectl runs a kubectl command.
func (r *Runner) Kubectl(ctx context.Context, args ...string) (*Result, error) {
	return r.RunSilent(ctx, "kubectl", args...)
}

// Helm runs a helm command.
func (r *Runner) Helm(ctx context.Context, args ...string) (*Result, error) {
	return r.RunSilent(ctx, "helm", args...)
}

// CommandExists checks if a command is available in PATH.
func CommandExists(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}
