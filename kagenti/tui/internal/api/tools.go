package api

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// ListTools lists tools in the given namespace (or client's default).
func (c *Client) ListTools(namespace string) (*ToolListResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/tools?namespace=%s", ns))
	req, err := c.newRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	var resp ToolListResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetTool gets details for a specific tool.
func (c *Client) GetTool(namespace, name string) (map[string]any, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/tools/%s/%s", ns, name))
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

// CreateTool creates a new tool.
func (c *Client) CreateTool(tool *CreateToolRequest) (*CreateToolResponse, error) {
	body, err := json.Marshal(tool)
	if err != nil {
		return nil, err
	}
	url := c.apiURL("/tools")
	req, err := c.newRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	var resp CreateToolResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// DeleteTool deletes a tool by name and namespace.
func (c *Client) DeleteTool(namespace, name string) (*DeleteResponse, error) {
	ns := namespace
	if ns == "" {
		ns = c.Namespace
	}
	url := c.apiURL(fmt.Sprintf("/tools/%s/%s", ns, name))
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
