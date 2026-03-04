package components

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/command"
)

func runeMsg(s string) tea.KeyMsg {
	return tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(s)}
}

func keyMsg(t tea.KeyType) tea.KeyMsg {
	return tea.KeyMsg{Type: t}
}

func TestCommandInput_ActivateAndDeactivate(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)

	if c.Active() {
		t.Fatal("should start inactive")
	}

	c.Activate()
	if !c.Active() {
		t.Fatal("should be active after Activate()")
	}
	if c.input != "/" {
		t.Errorf("expected input '/', got %q", c.input)
	}
	// All commands should match on empty prefix.
	if len(c.matches) != len(reg.All()) {
		t.Errorf("expected %d matches on activation, got %d", len(reg.All()), len(c.matches))
	}

	c.Deactivate()
	if c.Active() {
		t.Fatal("should be inactive after Deactivate()")
	}
	if c.input != "" {
		t.Errorf("expected empty input after deactivate, got %q", c.input)
	}
}

func TestCommandInput_TypeAndFilter(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Type "ag" → should filter to "agents" and "agent".
	c.Update(runeMsg("a"))
	c.Update(runeMsg("g"))

	if c.input != "/ag" {
		t.Errorf("expected input '/ag', got %q", c.input)
	}

	for _, m := range c.matches {
		if !strings.HasPrefix(m.Name, "ag") {
			t.Errorf("match %q doesn't start with 'ag'", m.Name)
		}
	}
	if len(c.matches) != 2 { // "agents" and "agent"
		t.Errorf("expected 2 matches for 'ag', got %d", len(c.matches))
	}
}

func TestCommandInput_BackspaceDeactivates(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Backspace on "/" should deactivate.
	c.Update(keyMsg(tea.KeyBackspace))
	if c.Active() {
		t.Fatal("backspace on '/' should deactivate")
	}
}

func TestCommandInput_BackspaceUpdatesFilter(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	c.Update(runeMsg("a"))
	c.Update(runeMsg("g"))
	if c.input != "/ag" {
		t.Fatalf("expected '/ag', got %q", c.input)
	}

	c.Update(keyMsg(tea.KeyBackspace))
	if c.input != "/a" {
		t.Errorf("expected '/a' after backspace, got %q", c.input)
	}
	// Should re-match with prefix "a": agents, agent.
	for _, m := range c.matches {
		if !strings.HasPrefix(m.Name, "a") {
			t.Errorf("match %q doesn't start with 'a'", m.Name)
		}
	}
}

func TestCommandInput_EscDeactivates(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	c.Update(keyMsg(tea.KeyEsc))
	if c.Active() {
		t.Fatal("Esc should deactivate")
	}
}

func TestCommandInput_ArrowNavigation(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	if c.selected != -1 {
		t.Fatalf("expected selected=-1, got %d", c.selected)
	}

	// Down arrow should select first item.
	c.Update(keyMsg(tea.KeyDown))
	if c.selected != 0 {
		t.Errorf("expected selected=0 after Down, got %d", c.selected)
	}

	// Down again should select second item.
	c.Update(keyMsg(tea.KeyDown))
	if c.selected != 1 {
		t.Errorf("expected selected=1 after second Down, got %d", c.selected)
	}

	// Up should go back.
	c.Update(keyMsg(tea.KeyUp))
	if c.selected != 0 {
		t.Errorf("expected selected=0 after Up, got %d", c.selected)
	}

	// Up from 0 should wrap to last.
	c.Update(keyMsg(tea.KeyUp))
	if c.selected != len(c.matches)-1 {
		t.Errorf("expected wrap to last (%d), got %d", len(c.matches)-1, c.selected)
	}
}

func TestCommandInput_TabCompletion(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Type "tool" → matches "tools" and "tool".
	for _, ch := range "tool" {
		c.Update(runeMsg(string(ch)))
	}
	if len(c.matches) != 2 {
		t.Fatalf("expected 2 matches for 'tool', got %d", len(c.matches))
	}

	// Select first match and tab-complete.
	c.Update(keyMsg(tea.KeyDown))
	selectedName := c.matches[c.selected].Name
	c.Update(keyMsg(tea.KeyTab))

	if !strings.HasPrefix(c.input, "/"+selectedName) {
		t.Errorf("expected tab-completion to '/%s...', got %q", selectedName, c.input)
	}
}

func TestCommandInput_SingleMatchTabComplete(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Type "qui" → should match only "quit".
	for _, ch := range "qui" {
		c.Update(runeMsg(string(ch)))
	}
	if len(c.matches) != 1 {
		t.Fatalf("expected 1 match for 'qui', got %d", len(c.matches))
	}

	// Tab with no selection but single match should complete.
	c.Update(keyMsg(tea.KeyTab))
	if c.input != "/quit" {
		t.Errorf("expected '/quit', got %q", c.input)
	}
}

func TestCommandInput_EnterSubmitsCommand(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Type "agents" and press Enter.
	for _, ch := range "agents" {
		c.Update(runeMsg(string(ch)))
	}
	cmd := c.Update(keyMsg(tea.KeyEnter))

	if c.Active() {
		t.Fatal("should deactivate after Enter")
	}

	// Execute the returned command to get the message.
	if cmd == nil {
		t.Fatal("expected a command from Enter")
	}
	msg := cmd()
	submitted, ok := msg.(CommandSubmittedMsg)
	if !ok {
		t.Fatalf("expected CommandSubmittedMsg, got %T", msg)
	}
	if submitted.Command != "agents" {
		t.Errorf("expected command 'agents', got %q", submitted.Command)
	}
}

func TestCommandInput_EnterSubmitsSelected(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Navigate to select a command, then press Enter.
	c.Update(keyMsg(tea.KeyDown)) // select first
	selectedName := c.matches[c.selected].Name

	cmd := c.Update(keyMsg(tea.KeyEnter))
	if cmd == nil {
		t.Fatal("expected a command from Enter with selection")
	}
	msg := cmd()
	submitted, ok := msg.(CommandSubmittedMsg)
	if !ok {
		t.Fatalf("expected CommandSubmittedMsg, got %T", msg)
	}
	if submitted.Command != selectedName {
		t.Errorf("expected command %q, got %q", selectedName, submitted.Command)
	}
}

func TestCommandInput_SpaceClearsMatches(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	for _, ch := range "chat" {
		c.Update(runeMsg(string(ch)))
	}
	c.Update(keyMsg(tea.KeySpace))

	if c.matches != nil {
		t.Errorf("expected nil matches after space (arg mode), got %d", len(c.matches))
	}
	if c.input != "/chat " {
		t.Errorf("expected '/chat ', got %q", c.input)
	}
}

func TestCommandInput_EnterWithArg(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	// Type "chat my-agent" and press Enter.
	for _, ch := range "chat" {
		c.Update(runeMsg(string(ch)))
	}
	c.Update(keyMsg(tea.KeySpace))
	for _, ch := range "my-agent" {
		c.Update(runeMsg(string(ch)))
	}
	cmd := c.Update(keyMsg(tea.KeyEnter))

	if cmd == nil {
		t.Fatal("expected a command from Enter")
	}
	msg := cmd()
	submitted := msg.(CommandSubmittedMsg)
	if submitted.Command != "chat" || submitted.Args != "my-agent" {
		t.Errorf("expected chat/my-agent, got %q/%q", submitted.Command, submitted.Args)
	}
}

func TestCommandInput_InactiveIgnoresInput(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)

	// Not activated — Update should be a no-op.
	cmd := c.Update(runeMsg("x"))
	if cmd != nil {
		t.Error("expected nil command when inactive")
	}
	if c.input != "" {
		t.Errorf("expected empty input when inactive, got %q", c.input)
	}
}

func TestCommandInput_ViewEmptyWhenInactive(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)

	if v := c.View(); v != "" {
		t.Errorf("expected empty view when inactive, got %q", v)
	}
}

func TestCommandInput_ViewShowsDropdown(t *testing.T) {
	reg := command.NewRegistry()
	c := NewCommandInput(reg)
	c.Activate()

	view := c.View()
	if !strings.Contains(view, "/") {
		t.Error("expected view to contain prompt")
	}
	if !strings.Contains(view, "agents") {
		t.Error("expected view to contain 'agents' in dropdown")
	}
}
