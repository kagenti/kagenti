package api

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// GetAgentCard fetches the A2A agent card.
func (c *Client) GetAgentCard(namespace, name string) (*AgentCardResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	u := c.apiURL(fmt.Sprintf("/chat/%s/%s/agent-card", url.PathEscape(ns), url.PathEscape(name)))
	req, err := c.newRequest("GET", u, nil)
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
	u := c.apiURL(fmt.Sprintf("/chat/%s/%s/send", url.PathEscape(ns), url.PathEscape(name)))
	req, err := c.newRequest("POST", u, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	var resp ChatResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// streamClient is used for SSE connections with no overall timeout.
var streamClient = &http.Client{
	Timeout: 0, // no overall timeout; we use transport-level timeouts
	Transport: &http.Transport{
		ResponseHeaderTimeout: 30 * time.Second, // fail fast if agent never responds
	},
}

// StreamChat opens an SSE connection and sends events to the returned channel.
// The channel is closed when the stream ends or on error.
func (c *Client) StreamChat(namespace, name string, chatReq *ChatRequest) (<-chan ChatStreamEvent, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	bodyBytes, err := json.Marshal(chatReq)
	if err != nil {
		return nil, err
	}
	u := c.apiURL(fmt.Sprintf("/chat/%s/%s/stream", url.PathEscape(ns), url.PathEscape(name)))

	doStream := func() (*http.Response, error) {
		req, err := c.newRequest("POST", u, bytes.NewReader(bodyBytes))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Accept", "text/event-stream")
		return streamClient.Do(req)
	}

	staleToken := c.GetToken()
	resp, err := doStream()
	if err != nil {
		return nil, fmt.Errorf("stream request failed: %w", err)
	}

	// On 401, attempt a single token refresh and retry.
	if resp.StatusCode == http.StatusUnauthorized && c.canRefresh() {
		resp.Body.Close()
		if refreshErr := c.refreshAccessToken(staleToken); refreshErr == nil {
			resp, err = doStream()
			if err != nil {
				return nil, fmt.Errorf("stream retry failed: %w", err)
			}
		}
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, maxResponseBody))
		resp.Body.Close()
		if len(respBody) > 0 {
			return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
		}
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	ch := make(chan ChatStreamEvent, 16)

	// Send initial debug info about the connection
	ch <- ChatStreamEvent{Debug: fmt.Sprintf("POST %s → HTTP %d", u, resp.StatusCode)}
	ch <- ChatStreamEvent{Debug: fmt.Sprintf("Content-Type: %s", resp.Header.Get("Content-Type"))}

	go func() {
		defer resp.Body.Close()
		defer close(ch)

		scanner := bufio.NewScanner(resp.Body)
		lineNum := 0
		for scanner.Scan() {
			line := scanner.Text()
			lineNum++
			if !strings.HasPrefix(line, "data: ") {
				if strings.TrimSpace(line) != "" {
					ch <- ChatStreamEvent{Debug: fmt.Sprintf("line %d (skipped): %s", lineNum, line)}
				}
				continue
			}
			data := line[6:]
			if data == "[DONE]" {
				ch <- ChatStreamEvent{Debug: "stream: [DONE]"}
				ch <- ChatStreamEvent{Done: true}
				return
			}
			var evt ChatStreamEvent
			if err := json.Unmarshal([]byte(data), &evt); err != nil {
				ch <- ChatStreamEvent{Debug: fmt.Sprintf("line %d (parse error): %s — raw: %s", lineNum, err, data)}
				continue
			}
			ch <- evt
		}
		if err := scanner.Err(); err != nil {
			ch <- ChatStreamEvent{Debug: fmt.Sprintf("scanner error: %s", err)}
		} else {
			ch <- ChatStreamEvent{Debug: "stream: EOF (connection closed)"}
		}
	}()

	return ch, nil
}
