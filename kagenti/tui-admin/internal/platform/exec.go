package platform

import (
	"context"
	"os/exec"
)

// execCmd creates an exec.Cmd — thin wrapper for testability.
func execCmd(ctx context.Context, name string, args ...string) *exec.Cmd {
	return exec.CommandContext(ctx, name, args...)
}
