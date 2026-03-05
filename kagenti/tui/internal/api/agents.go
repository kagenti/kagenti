package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
)

// ListAgents lists agents in the given namespace (or client's default).
func (c *Client) ListAgents(namespace string) (*AgentListResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	q := url.Values{"namespace": {ns}}
	u := c.apiURL("/agents?" + q.Encode())
	req, err := c.newRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	var resp AgentListResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetAgent gets details for a specific agent.
func (c *Client) GetAgent(namespace, name string) (map[string]any, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/agents/%s/%s", ns, name))
	req, err := c.newRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	var resp map[string]any
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return resp, nil
}

// CreateAgent creates a new agent.
func (c *Client) CreateAgent(agent *CreateAgentRequest) (*CreateAgentResponse, error) {
	body, err := json.Marshal(agent)
	if err != nil {
		return nil, err
	}
	url := c.apiURL("/agents")
	req, err := c.newRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	var resp CreateAgentResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// DeleteAgent deletes an agent by name and namespace.
func (c *Client) DeleteAgent(namespace, name string) (*DeleteResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/agents/%s/%s", ns, name))
	req, err := c.newRequest("DELETE", url, nil)
	if err != nil {
		return nil, err
	}
	var resp DeleteResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}
