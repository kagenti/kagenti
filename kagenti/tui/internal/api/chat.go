package api

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// GetAgentCard fetches the A2A agent card.
func (c *Client) GetAgentCard(namespace, name string) (*AgentCardResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/chat/%s/%s/agent-card", ns, name))
	req, err := c.newRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	var resp AgentCardResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// SendMessage sends a non-streaming chat message.
func (c *Client) SendMessage(namespace, name string, chatReq *ChatRequest) (*ChatResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	body, err := json.Marshal(chatReq)
	if err != nil {
		return nil, err
	}
	url := c.apiURL(fmt.Sprintf("/chat/%s/%s/send", ns, name))
	req, err := c.newRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	var resp ChatResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// StreamChat opens an SSE connection and sends events to the returned channel.
// The channel is closed when the stream ends or on error.
func (c *Client) StreamChat(namespace, name string, chatReq *ChatRequest) (<-chan ChatStreamEvent, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	body, err := json.Marshal(chatReq)
	if err != nil {
		return nil, err
	}
	url := c.apiURL(fmt.Sprintf("/chat/%s/%s/stream", ns, name))
	req, err := http.NewRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")

	// Use a client with a generous timeout for the initial connection.
	// Individual event reads are governed by the scanner in the goroutine.
	streamClient := &http.Client{
		Timeout: 0, // no overall timeout; we use transport-level timeouts
		Transport: &http.Transport{
			ResponseHeaderTimeout: 30 * time.Second, // fail fast if agent never responds
		},
	}
	resp, err := streamClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("stream request failed: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if len(body) > 0 {
			return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
		}
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	ch := make(chan ChatStreamEvent, 16)
	go func() {
		defer resp.Body.Close()
		defer close(ch)

		scanner := bufio.NewScanner(resp.Body)
		for scanner.Scan() {
			line := scanner.Text()
			if !strings.HasPrefix(line, "data: ") {
				continue
			}
			data := line[6:]
			if data == "[DONE]" {
				ch <- ChatStreamEvent{Done: true}
				return
			}
			var evt ChatStreamEvent
			if err := json.Unmarshal([]byte(data), &evt); err != nil {
				continue
			}
			ch <- evt
		}
	}()

	return ch, nil
}
