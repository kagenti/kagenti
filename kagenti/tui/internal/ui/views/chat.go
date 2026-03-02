package views

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
	"github.com/kagenti/kagenti/kagenti/tui/internal/theme"
)

// chatMessage is a message in the chat history.
type chatMessage struct {
	role    string // "user" or "assistant"
	content string
}

// ChatView is the interactive chat view with SSE streaming.
type ChatView struct {
	client    *api.Client
	width     int
	height    int
	agentName string
	agentCard *api.AgentCardResponse
	messages  []chatMessage
	input     string
	sessionID string
	streaming bool
	streamBuf string
	err       error
}

// NewChatView creates a new chat view.
func NewChatView(client *api.Client) ChatView {
	return ChatView{client: client}
}

// SetSize sets the view dimensions.
func (v *ChatView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

// SetAgent sets the agent to chat with.
func (v *ChatView) SetAgent(name string) {
	v.agentName = name
	v.messages = nil
	v.input = ""
	v.sessionID = ""
	v.streaming = false
	v.streamBuf = ""
	v.agentCard = nil
	v.err = nil
}

type agentCardLoadedMsg struct {
	card *api.AgentCardResponse
	err  error
}

type chatStreamEventMsg struct {
	event api.ChatStreamEvent
}

type chatStreamDoneMsg struct{}

// Init fetches the agent card.
func (v ChatView) Init() tea.Cmd {
	client := v.client
	name := v.agentName
	return func() tea.Msg {
		card, err := client.GetAgentCard("", name)
		if err != nil {
			return agentCardLoadedMsg{err: err}
		}
		return agentCardLoadedMsg{card: card}
	}
}

// Update handles messages.
func (v ChatView) Update(msg tea.Msg) (ChatView, tea.Cmd) {
	switch msg := msg.(type) {
	case agentCardLoadedMsg:
		v.agentCard = msg.card
		v.err = msg.err

	case chatStreamEventMsg:
		evt := msg.event
		if evt.Done {
			return v, func() tea.Msg { return chatStreamDoneMsg{} }
		}
		if evt.Error != "" {
			v.err = fmt.Errorf("%s", evt.Error)
			v.streaming = false
			return v, nil
		}
		if evt.Content != "" {
			v.streamBuf += evt.Content
		}
		if evt.SessionID != "" {
			v.sessionID = evt.SessionID
		}
		// Continue reading stream
		return v, nil

	case chatStreamDoneMsg:
		v.streaming = false
		if v.streamBuf != "" {
			v.messages = append(v.messages, chatMessage{role: "assistant", content: v.streamBuf})
			v.streamBuf = ""
		}
		return v, nil

	case tea.KeyMsg:
		if v.streaming {
			return v, nil // ignore input while streaming
		}

		switch msg.Type {
		case tea.KeyEsc:
			return v, func() tea.Msg {
				return NavigateMsg{Target: "home"}
			}

		case tea.KeyEnter:
			if v.input != "" {
				text := v.input
				v.input = ""
				v.messages = append(v.messages, chatMessage{role: "user", content: text})
				v.streaming = true
				v.streamBuf = ""
				return v, v.sendMessage(text)
			}

		case tea.KeyBackspace:
			if len(v.input) > 0 {
				v.input = v.input[:len(v.input)-1]
			}

		case tea.KeyRunes:
			r := msg.Runes
			if len(r) > 0 {
				v.input += string(r)
			}
		}
	}
	return v, nil
}

// sendMessage starts the SSE stream.
func (v *ChatView) sendMessage(text string) tea.Cmd {
	client := v.client
	agentName := v.agentName
	sessionID := v.sessionID
	return func() tea.Msg {
		chatReq := &api.ChatRequest{
			Message:   text,
			SessionID: sessionID,
		}

		// Try streaming first
		ch, err := client.StreamChat("", agentName, chatReq)
		if err != nil {
			// Fall back to non-streaming
			resp, err2 := client.SendMessage("", agentName, chatReq)
			if err2 != nil {
				return chatStreamEventMsg{event: api.ChatStreamEvent{Error: err2.Error()}}
			}
			return chatStreamEventMsg{event: api.ChatStreamEvent{
				Content:   resp.Content,
				SessionID: resp.SessionID,
				Done:      true,
			}}
		}

		// Read first event from stream
		evt, ok := <-ch
		if !ok {
			return chatStreamDoneMsg{}
		}
		// Start a goroutine to pump remaining events
		go func() {
			for range ch {
				// Events are consumed by the pumper; we rely on the
				// tea.Cmd chain below to pull them one at a time.
			}
		}()
		return chatStreamEventMsg{event: evt}
	}
}

// View renders the chat view.
func (v ChatView) View() string {
	var b strings.Builder

	// Header
	b.WriteString(theme.TitleStyle.Render("Chat: "+v.agentName) + "\n")

	if v.err != nil && v.agentCard == nil {
		b.WriteString(theme.ErrorStyle.Render(fmt.Sprintf("  Error: %s", v.err.Error())) + "\n")
	}

	if v.agentCard != nil {
		desc := v.agentCard.Description
		if desc == "" {
			desc = "No description"
		}
		b.WriteString(theme.MutedStyle.Render(fmt.Sprintf("  %s (v%s)", desc, v.agentCard.Version)) + "\n")

		if len(v.agentCard.Skills) > 0 {
			var skillNames []string
			for _, s := range v.agentCard.Skills {
				if name, ok := s["name"].(string); ok {
					skillNames = append(skillNames, name)
				}
			}
			if len(skillNames) > 0 {
				b.WriteString(theme.MutedStyle.Render("  Skills: "+strings.Join(skillNames, ", ")) + "\n")
			}
		}
	}
	b.WriteString("\n")

	// Messages
	for _, m := range v.messages {
		if m.role == "user" {
			b.WriteString(theme.LabelStyle.Render("  You: ") + m.content + "\n")
		} else {
			b.WriteString(theme.SuccessStyle.Render("  Agent: ") + m.content + "\n")
		}
		b.WriteString("\n")
	}

	// Streaming buffer
	if v.streaming && v.streamBuf != "" {
		b.WriteString(theme.SuccessStyle.Render("  Agent: ") + v.streamBuf + theme.MutedStyle.Render("▌") + "\n\n")
	} else if v.streaming {
		b.WriteString(theme.MutedStyle.Render("  Thinking...") + "\n\n")
	}

	// Input
	if !v.streaming {
		b.WriteString(theme.LabelStyle.Render("  > ") + v.input + theme.MutedStyle.Render("█") + "\n")
	}

	b.WriteString("\n" + theme.MutedStyle.Render("  Esc back  •  Enter send"))

	return b.String()
}
