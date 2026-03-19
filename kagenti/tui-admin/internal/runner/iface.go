package runner

import "context"

// Executor defines the interface for running commands.
// This allows mocking in tests without shelling out.
type Executor interface {
	Run(ctx context.Context, name string, args ...string) (*Result, error)
	RunSilent(ctx context.Context, name string, args ...string) (*Result, error)
}

// Ensure Runner implements Executor.
var _ Executor = (*Runner)(nil)
