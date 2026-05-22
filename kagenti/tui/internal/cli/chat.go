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

			// Try streaming first.
			ch, err := ctx.Client.StreamChat(ns, agent, chatReq)
			if err == nil {
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

			// Fall back to non-streaming.
			resp, err := ctx.Client.SendMessage(ns, agent, chatReq)
			if err != nil {
				return fmt.Errorf("sending message: %w", err)
			}
			fmt.Println(resp.Content)
			if resp.SessionID != "" {
				fmt.Fprintf(os.Stderr, "session-id: %s\n", resp.SessionID)
			}
			return nil
		},
	}

	cmd.Flags().StringVarP(&message, "message", "m", "", "Message to send (required)")
	cmd.Flags().StringVar(&sessionID, "session-id", "", "Chat session ID")
	_ = cmd.MarkFlagRequired("message")

	return cmd
}
