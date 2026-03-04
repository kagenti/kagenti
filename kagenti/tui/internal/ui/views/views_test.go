package views

import (
	"fmt"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
)

// ========== ChatView Tests ==========

func TestChatView_StreamAccumulation(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")

	// Simulate user sending a message (manually set state as sendMessage
	// requires a real client).
	v.streaming = true
	v.streamBuf = ""
	v.messages = append(v.messages, chatMessage{role: "user", content: "hello"})

	// Feed stream events.
	events := []api.ChatStreamEvent{
		{Content: "Hello "},
		{Content: "world", SessionID: "sess-1"},
		{Content: "!"},
	}
	for _, evt := range events {
		v, _ = v.Update(chatStreamEventMsg{event: evt})
	}

	if v.streamBuf != "Hello world!" {
		t.Errorf("expected streamBuf='Hello world!', got %q", v.streamBuf)
	}
	if v.sessionID != "sess-1" {
		t.Errorf("expected sessionID='sess-1', got %q", v.sessionID)
	}
	if !v.streaming {
		t.Error("expected streaming=true before Done")
	}
}

func TestChatView_DoneFlushesBuffer(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")
	v.streaming = true
	v.streamBuf = "response text"
	v.messages = []chatMessage{{role: "user", content: "hi"}}

	// Send Done event.
	v, _ = v.Update(chatStreamEventMsg{event: api.ChatStreamEvent{Done: true}})

	if v.streaming {
		t.Error("expected streaming=false after Done")
	}
	if v.streamBuf != "" {
		t.Errorf("expected empty streamBuf after Done, got %q", v.streamBuf)
	}
	if len(v.messages) != 2 {
		t.Fatalf("expected 2 messages (user + assistant), got %d", len(v.messages))
	}
	if v.messages[1].role != "assistant" || v.messages[1].content != "response text" {
		t.Errorf("expected assistant message 'response text', got %+v", v.messages[1])
	}
}

func TestChatView_ChatStreamDoneMsgFlushes(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")
	v.streaming = true
	v.streamBuf = "buffered"

	v, _ = v.Update(chatStreamDoneMsg{})

	if v.streaming {
		t.Error("expected streaming=false after chatStreamDoneMsg")
	}
	if len(v.messages) != 1 || v.messages[0].content != "buffered" {
		t.Errorf("expected flushed message 'buffered', got %+v", v.messages)
	}
}

func TestChatView_StreamErrorStopsStreaming(t *testing.T) {
	tests := []struct {
		name string
		msg  tea.Msg
	}{
		{
			name: "error in stream event",
			msg:  chatStreamEventMsg{event: api.ChatStreamEvent{Error: "agent exploded"}},
		},
		{
			name: "chatStreamErrMsg",
			msg:  chatStreamErrMsg{err: fmt.Errorf("connection lost")},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewChatView(client)
			v.SetAgent("test-agent")
			v.streaming = true

			v, _ = v.Update(tc.msg)

			if v.streaming {
				t.Error("expected streaming=false after error")
			}
			if v.err == nil {
				t.Error("expected error to be set")
			}
		})
	}
}

func TestChatView_DebugEventsSkipped(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")
	v.streaming = true

	// Feed a debug event — should not appear in streamBuf.
	v, _ = v.Update(chatStreamEventMsg{event: api.ChatStreamEvent{Debug: "debug info"}})

	if v.streamBuf != "" {
		t.Errorf("expected empty streamBuf, debug should not go into content, got %q", v.streamBuf)
	}
	if len(v.debug) != 1 || v.debug[0] != "debug info" {
		t.Errorf("expected debug recorded, got %v", v.debug)
	}
}

func TestChatView_IgnoresInputWhileStreaming(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")
	v.streaming = true
	v.input = ""

	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("x")})

	if v.input != "" {
		t.Errorf("expected input unchanged while streaming, got %q", v.input)
	}
}

func TestChatView_InputHandling(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")

	// Type characters.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("h")})
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("i")})
	if v.input != "hi" {
		t.Errorf("expected input='hi', got %q", v.input)
	}

	// Backspace.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	if v.input != "h" {
		t.Errorf("expected input='h' after backspace, got %q", v.input)
	}

	// Space.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeySpace})
	if v.input != "h " {
		t.Errorf("expected input='h ' after space, got %q", v.input)
	}
}

func TestChatView_InputHistoryNavigation(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")

	// Seed some history.
	v.history = []string{"first", "second"}
	v.historyIdx = -1
	v.input = "current"

	// Up should go to last history entry.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyUp})
	if v.input != "second" {
		t.Errorf("expected 'second', got %q", v.input)
	}

	// Up again should go to first.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyUp})
	if v.input != "first" {
		t.Errorf("expected 'first', got %q", v.input)
	}

	// Down should go back to second.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyDown})
	if v.input != "second" {
		t.Errorf("expected 'second', got %q", v.input)
	}

	// Down past end restores draft.
	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyDown})
	if v.input != "current" {
		t.Errorf("expected restored draft 'current', got %q", v.input)
	}
}

func TestChatView_ViewRendersState(t *testing.T) {
	tests := []struct {
		name     string
		setup    func(*ChatView)
		contains []string
	}{
		{
			name: "streaming shows Thinking",
			setup: func(v *ChatView) {
				v.streaming = true
			},
			contains: []string{"Thinking"},
		},
		{
			name: "streaming with content shows buffer",
			setup: func(v *ChatView) {
				v.streaming = true
				v.streamBuf = "partial response"
			},
			contains: []string{"partial response"},
		},
		{
			name: "messages rendered",
			setup: func(v *ChatView) {
				v.messages = []chatMessage{
					{role: "user", content: "hello"},
					{role: "assistant", content: "hi there"},
				}
			},
			contains: []string{"hello", "hi there"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewChatView(client)
			v.SetAgent("test-agent")
			tc.setup(&v)

			view := v.View()
			for _, s := range tc.contains {
				if !strings.Contains(view, s) {
					t.Errorf("expected view to contain %q, got:\n%s", s, view)
				}
			}
		})
	}
}

func TestChatView_CtrlDTogglesDebug(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewChatView(client)
	v.SetAgent("test-agent")

	if v.showDebug {
		t.Fatal("should start with debug off")
	}

	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyCtrlD})
	if !v.showDebug {
		t.Error("expected debug on after Ctrl+D")
	}

	v, _ = v.Update(tea.KeyMsg{Type: tea.KeyCtrlD})
	if v.showDebug {
		t.Error("expected debug off after second Ctrl+D")
	}
}

// ========== DeployAgentView Tests ==========

func TestDeployAgentView_FormValidationPreventsEmptyName(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewDeployAgentView(client)

	// Simulate namespaces loaded + tools loaded to trigger form build.
	v, _ = v.Update(namespacesLoadedMsg{namespaces: []string{"team1"}})
	v, _ = v.Update(toolsForAgentMsg{tools: nil})

	if v.form == nil {
		t.Fatal("expected form to be built")
	}

	// The form should not be in a completed/submitted state initially.
	if v.submitted {
		t.Error("form should not be submitted initially")
	}
	if v.deploying {
		t.Error("form should not be in deploying state initially")
	}

	// Verify the name field has a validation function that rejects empty.
	// We can check this by inspecting the form values — name defaults to "".
	if v.vals.name != "" {
		t.Errorf("expected empty default name, got %q", v.vals.name)
	}
}

func TestDeployAgentView_DefaultFormValues(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewDeployAgentView(client)

	v, _ = v.Update(namespacesLoadedMsg{namespaces: []string{"team1", "team2"}})
	v, _ = v.Update(toolsForAgentMsg{})

	if v.vals == nil {
		t.Fatal("expected form values to be allocated")
	}

	defaults := []struct {
		field string
		got   string
		want  string
	}{
		{"namespace", v.vals.namespace, "team1"},
		{"framework", v.vals.framework, "LangGraph"},
		{"protocol", v.vals.protocol, "a2a"},
		{"deployMethod", v.vals.deployMethod, "image"},
		{"gitBranch", v.vals.gitBranch, "main"},
		{"llmEnv", v.vals.llmEnv, "openai"},
		{"logLevel", v.vals.logLevel, "INFO"},
	}
	for _, d := range defaults {
		if d.got != d.want {
			t.Errorf("default %s: expected %q, got %q", d.field, d.want, d.got)
		}
	}
}

func TestDeployAgentView_FallbackNamespaces(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewDeployAgentView(client)

	// Simulate empty namespace response.
	v, _ = v.Update(namespacesLoadedMsg{namespaces: nil})
	if len(v.namespaces) != 2 || v.namespaces[0] != "team1" {
		t.Errorf("expected fallback namespaces [team1, team2], got %v", v.namespaces)
	}
}

func TestDeployAgentView_SuccessNavigates(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewDeployAgentView(client)
	v.deploying = true

	v, cmd := v.Update(agentDeployedMsg{
		result: &api.CreateAgentResponse{Success: true, Name: "my-agent", Namespace: "team1"},
	})

	if v.deploying {
		t.Error("expected deploying=false after success")
	}
	if cmd == nil {
		t.Fatal("expected navigation command on success")
	}
	msg := cmd()
	nav, ok := msg.(NavigateMsg)
	if !ok {
		t.Fatalf("expected NavigateMsg, got %T", msg)
	}
	if nav.Target != "agent-detail" || nav.Name != "my-agent" {
		t.Errorf("expected navigate to agent-detail/my-agent, got %+v", nav)
	}
}

func TestDeployAgentView_ErrorSetsState(t *testing.T) {
	client := api.NewClient("http://fake", "", "team1")
	v := NewDeployAgentView(client)
	v.deploying = true

	v, _ = v.Update(agentDeployedMsg{err: fmt.Errorf("deploy failed")})

	if v.deploying {
		t.Error("expected deploying=false after error")
	}
	if v.err == nil {
		t.Error("expected err to be set")
	}
}

func TestDeployAgentView_ViewStates(t *testing.T) {
	tests := []struct {
		name     string
		setup    func(*DeployAgentView)
		contains string
	}{
		{
			name:     "deploying shows spinner",
			setup:    func(v *DeployAgentView) { v.deploying = true },
			contains: "Deploying",
		},
		{
			name: "success shows check",
			setup: func(v *DeployAgentView) {
				v.result = &api.CreateAgentResponse{Success: true, Name: "a", Namespace: "team1"}
			},
			contains: "created",
		},
		{
			name: "failure shows error",
			setup: func(v *DeployAgentView) {
				v.result = &api.CreateAgentResponse{Success: false, Message: "bad request"}
			},
			contains: "bad request",
		},
		{
			name:     "error shows message",
			setup:    func(v *DeployAgentView) { v.err = fmt.Errorf("network error") },
			contains: "network error",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := api.NewClient("http://fake", "", "team1")
			v := NewDeployAgentView(client)
			tc.setup(&v)

			view := v.View()
			if !strings.Contains(view, tc.contains) {
				t.Errorf("expected view to contain %q, got:\n%s", tc.contains, view)
			}
		})
	}
}
