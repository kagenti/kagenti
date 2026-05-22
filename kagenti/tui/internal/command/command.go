// Package command provides the slash command registry and parsing.
package command

import "strings"

// Command represents a registered slash command.
type Command struct {
	Name        string
	Description string
	HasArg      bool   // whether the command takes an argument
	ArgHint     string // e.g. "<name>", "<agent>"
}

// Registry holds all available commands.
type Registry struct {
	commands []Command
}

// NewRegistry creates a registry with the default commands.
func NewRegistry() *Registry {
	return &Registry{
		commands: []Command{
			{Name: "agents", Description: "List agents in current namespace"},
			{Name: "agent", Description: "Show agent details", HasArg: true, ArgHint: "<name>"},
			{Name: "tools", Description: "List tools in current namespace"},
			{Name: "tool", Description: "Show tool details", HasArg: true, ArgHint: "<name>"},
			{Name: "chat", Description: "Chat with an agent", HasArg: true, ArgHint: "<agent>"},
			{Name: "deploy", Description: "Deploy agent or tool", HasArg: true, ArgHint: "agent|tool"},
			{Name: "delete", Description: "Delete agent or tool", HasArg: true, ArgHint: "<type> <name>"},
			{Name: "ns", Description: "Switch namespace", HasArg: true, ArgHint: "[name]"},
			{Name: "login", Description: "Authenticate with Keycloak"},
			{Name: "logout", Description: "Clear authentication token"},
			{Name: "status", Description: "Return to status dashboard"},
			{Name: "help", Description: "Show all commands"},
			{Name: "quit", Description: "Exit"},
		},
	}
}

// All returns all registered commands.
func (r *Registry) All() []Command {
	return r.commands
}

// Match returns commands whose name starts with the given prefix.
func (r *Registry) Match(prefix string) []Command {
	prefix = strings.ToLower(strings.TrimLeft(prefix, "/"))
	if prefix == "" {
		return r.commands
	}
	var matches []Command
	for _, cmd := range r.commands {
		if strings.HasPrefix(cmd.Name, prefix) {
			matches = append(matches, cmd)
		}
	}
	return matches
}

// ParseInput parses a raw command string into command name and args.
// Input should start with "/".
func ParseInput(input string) (cmd string, args string) {
	input = strings.TrimSpace(input)
	if !strings.HasPrefix(input, "/") {
		return "", ""
	}
	input = input[1:] // strip "/"
	parts := strings.SplitN(input, " ", 2)
	cmd = strings.ToLower(parts[0])
	if len(parts) > 1 {
		args = strings.TrimSpace(parts[1])
	}
	return
}
