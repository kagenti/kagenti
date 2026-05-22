package components

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/kagenti/kagenti/kagenti/tui/internal/command"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// CommandInput is the / command input with autocomplete dropdown.
type CommandInput struct {
	input    string
	active   bool
	cursor   int
	selected int // index in matches, -1 = none
	registry *command.Registry
	matches  []command.Command
}

// NewCommandInput creates a new command input.
func NewCommandInput(registry *command.Registry) CommandInput {
	return CommandInput{
		registry: registry,
		selected: -1,
	}
}

// CommandSubmittedMsg is sent when a command is submitted.
type CommandSubmittedMsg struct {
	Command string
	Args    string
}

// Active returns whether the command input is focused.
func (c *CommandInput) Active() bool {
	return c.active
}

// Activate focuses the command input.
func (c *CommandInput) Activate() {
	c.active = true
	c.input = "/"
	c.cursor = 1
	c.selected = -1
	c.matches = c.registry.Match("")
}

// Deactivate clears and unfocuses the input.
func (c *CommandInput) Deactivate() {
	c.active = false
	c.input = ""
	c.cursor = 0
	c.selected = -1
	c.matches = nil
}

// Update handles input events.
func (c *CommandInput) Update(msg tea.Msg) tea.Cmd {
	if !c.active {
		return nil
	}

	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.Type {
		case tea.KeyEsc:
			c.Deactivate()
			return nil

		case tea.KeyEnter:
			input := c.input
			if c.selected >= 0 && c.selected < len(c.matches) {
				input = "/" + c.matches[c.selected].Name
			}
			c.Deactivate()
			cmd, args := command.ParseInput(input)
			if cmd != "" {
				return func() tea.Msg {
					return CommandSubmittedMsg{Command: cmd, Args: args}
				}
			}
			return nil

		case tea.KeyUp:
			if len(c.matches) > 0 {
				if c.selected <= 0 {
					c.selected = len(c.matches) - 1
				} else {
					c.selected--
				}
			}
			return nil

		case tea.KeyDown:
			if len(c.matches) > 0 {
				if c.selected >= len(c.matches)-1 {
					c.selected = 0
				} else {
					c.selected++
				}
			}
			return nil

		case tea.KeyTab:
			if c.selected >= 0 && c.selected < len(c.matches) {
				match := c.matches[c.selected]
				c.input = "/" + match.Name
				if match.HasArg {
					c.input += " "
				}
				c.cursor = len(c.input)
				c.selected = -1
				c.matches = c.registry.Match(c.input[1:])
			} else if len(c.matches) == 1 {
				match := c.matches[0]
				c.input = "/" + match.Name
				if match.HasArg {
					c.input += " "
				}
				c.cursor = len(c.input)
				c.selected = -1
				c.matches = nil
			}
			return nil

		case tea.KeyBackspace:
			if len(c.input) > 0 {
				c.input = c.input[:len(c.input)-1]
				c.cursor = len(c.input)
				if len(c.input) == 0 {
					c.Deactivate()
					return nil
				}
				c.selected = -1
				if !strings.Contains(c.input[1:], " ") {
					c.matches = c.registry.Match(c.input[1:])
				} else {
					c.matches = nil
				}
			}
			return nil

		case tea.KeySpace:
			c.input += " "
			c.cursor = len(c.input)
			c.selected = -1
			c.matches = nil
			return nil

		case tea.KeyRunes:
			c.input += string(msg.Runes)
			c.cursor = len(c.input)
			c.selected = -1
			if !strings.Contains(c.input[1:], " ") {
				c.matches = c.registry.Match(c.input[1:])
			} else {
				c.matches = nil
			}
			return nil
		}
	}
	return nil
}

// View renders the command input and autocomplete dropdown.
func (c *CommandInput) View() string {
	if !c.active {
		return ""
	}

	prompt := theme.CommandInputStyle.Render(c.input) + theme.MutedStyle.Render("█")

	if len(c.matches) == 0 {
		return prompt
	}

	var lines []string
	for i, cmd := range c.matches {
		name := "/" + cmd.Name
		if cmd.HasArg {
			name += " " + cmd.ArgHint
		}
		desc := theme.MutedStyle.Render(cmd.Description)
		line := fmt.Sprintf("  %-25s %s", name, desc)

		if i == c.selected {
			line = lipgloss.NewStyle().
				Bold(true).
				Foreground(theme.ColorPrimary).
				Render(fmt.Sprintf("▸ %-24s %s", name, cmd.Description))
		}
		lines = append(lines, line)
	}

	dropdown := strings.Join(lines, "\n")
	return prompt + "\n" + dropdown
}
