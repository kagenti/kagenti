package runner

import (
	"context"
	"fmt"
	"strings"
)

// MockExecutor is a test double for Executor. Register expected outputs
// with On() and it returns them in order.
type MockExecutor struct {
	Calls    []MockCall
	handlers map[string]func(args []string) (*Result, error)
}

// MockCall records a single invocation.
type MockCall struct {
	Name string
	Args []string
}

// NewMockExecutor creates a mock with no handlers (all calls return empty results).
func NewMockExecutor() *MockExecutor {
	return &MockExecutor{
		handlers: make(map[string]func(args []string) (*Result, error)),
	}
}

// On registers a handler for a command name. The handler receives the args
// and returns a Result or error. Use "*" as name to match all commands.
func (m *MockExecutor) On(name string, fn func(args []string) (*Result, error)) {
	m.handlers[name] = fn
}

// OnResult registers a simple result for a command name.
func (m *MockExecutor) OnResult(name string, stdout string, exitCode int) {
	m.handlers[name] = func(args []string) (*Result, error) {
		r := &Result{Stdout: stdout, ExitCode: exitCode}
		if exitCode != 0 {
			return r, fmt.Errorf("command %q exited with code %d", name, exitCode)
		}
		return r, nil
	}
}

func (m *MockExecutor) Run(ctx context.Context, name string, args ...string) (*Result, error) {
	m.Calls = append(m.Calls, MockCall{Name: name, Args: args})
	return m.handle(name, args)
}

func (m *MockExecutor) RunSilent(ctx context.Context, name string, args ...string) (*Result, error) {
	m.Calls = append(m.Calls, MockCall{Name: name, Args: args})
	return m.handle(name, args)
}

func (m *MockExecutor) handle(name string, args []string) (*Result, error) {
	// Try exact match first, then wildcard
	if fn, ok := m.handlers[name]; ok {
		return fn(args)
	}
	// Try matching with first arg (e.g. "kubectl" + "get" -> "kubectl get")
	if len(args) > 0 {
		key := name + " " + args[0]
		if fn, ok := m.handlers[key]; ok {
			return fn(args)
		}
	}
	if fn, ok := m.handlers["*"]; ok {
		return fn(args)
	}
	return &Result{Stdout: ""}, nil
}

// Called returns true if the named command was invoked.
func (m *MockExecutor) Called(name string) bool {
	for _, c := range m.Calls {
		if c.Name == name {
			return true
		}
	}
	return false
}

// CalledWith returns true if the named command was invoked with args containing substr.
func (m *MockExecutor) CalledWith(name, substr string) bool {
	for _, c := range m.Calls {
		if c.Name == name && strings.Contains(strings.Join(c.Args, " "), substr) {
			return true
		}
	}
	return false
}
