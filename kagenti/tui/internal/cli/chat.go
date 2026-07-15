package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
)

func newChatCmd(ctx *CLIContext) *cobra.Command {
	var (
		message   string
		sessionID string
	)

	cmd := &cobra.Command{
		Use:   "chat <agent>",
		Short: "Send a one-shot chat message to an agent",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			agent := args[0]
			ns, _ := cmd.Flags().GetString("namespace")

			chatReq := &api.ChatRequest{
				Message:   message,
				SessionID: sessionID,
			}

			// Consult the agent card to decide which transport to use.
			// A2A agents that declare streaming=false only implement
			// message/send and will 400 on message/stream, so we must
			// pick the right endpoint up front rather than try+fallback.
			useStreaming := true
			if card, err := ctx.Client.GetAgentCard(ns, agent); err == nil {
				useStreaming = card.Streaming
			} else {
				// Card fetch failed. Preserve prior behavior (attempt stream)
				// but let the user know we couldn't confirm.
				fmt.Fprintf(os.Stderr, "warning: could not determine streaming capability (%v), attempting stream\n", err)
			}

			if useStreaming {
				return runChatStream(ctx, ns, agent, chatReq)
			}
			return runChatSend(ctx, ns, agent, chatReq)
		},
	}

	cmd.Flags().StringVarP(&message, "message", "m", "", "Message to send (required)")
	cmd.Flags().StringVar(&sessionID, "session-id", "", "Chat session ID")
	_ = cmd.MarkFlagRequired("message")

	return cmd
}

// runChatStream streams a chat response over SSE, printing content chunks as
// they arrive.
func runChatStream(ctx *CLIContext, ns, agent string, chatReq *api.ChatRequest) error {
	ch, err := ctx.Client.StreamChat(ns, agent, chatReq)
	if err != nil {
		return fmt.Errorf("opening chat stream: %w", err)
	}
	var returnedSession string
	for evt := range ch {
		if evt.Error != "" {
			return fmt.Errorf("stream error: %s", evt.Error)
		}
		if evt.SessionID != "" {
			returnedSession = evt.SessionID
		}
		if evt.Content != "" {
			fmt.Print(evt.Content)
		}
		if evt.Done {
			fmt.Println()
			if returnedSession != "" {
				fmt.Fprintf(os.Stderr, "session-id: %s\n", returnedSession)
			}
			return nil
		}
	}
	fmt.Println()
	if returnedSession != "" {
		fmt.Fprintf(os.Stderr, "session-id: %s\n", returnedSession)
	}
	return nil
}

// runChatSend sends a non-streaming chat request and prints the full reply.
func runChatSend(ctx *CLIContext, ns, agent string, chatReq *api.ChatRequest) error {
	resp, err := ctx.Client.SendMessage(ns, agent, chatReq)
	if err != nil {
		return fmt.Errorf("sending message: %w", err)
	}
	fmt.Println(resp.Content)
	if resp.SessionID != "" {
		fmt.Fprintf(os.Stderr, "session-id: %s\n", resp.SessionID)
	}
	return nil
}
