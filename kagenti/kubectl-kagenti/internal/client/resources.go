// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// ResourceLabels mirrors API ResourceLabels.
type ResourceLabels struct {
	Protocol  []string `json:"protocol,omitempty"`
	Framework string   `json:"framework,omitempty"`
	Type      string   `json:"type,omitempty"`
}

// AgentSummary mirrors API AgentSummary.
type AgentSummary struct {
	Name          string         `json:"name"`
	Namespace     string         `json:"namespace"`
	Description   string         `json:"description"`
	Status        string         `json:"status"`
	Labels        ResourceLabels `json:"labels"`
	WorkloadType  string         `json:"workloadType,omitempty"`
	CreatedAt     string         `json:"createdAt,omitempty"`
}

// AgentListResponse mirrors API AgentListResponse.
type AgentListResponse struct {
	Items []AgentSummary `json:"items"`
}

// ToolSummary mirrors API ToolSummary.
type ToolSummary struct {
	Name          string         `json:"name"`
	Namespace     string         `json:"namespace"`
	Description   string         `json:"description"`
	Status        string         `json:"status"`
	Labels        ResourceLabels `json:"labels"`
	CreatedAt     string         `json:"createdAt,omitempty"`
	WorkloadType  string         `json:"workloadType,omitempty"`
}

// ToolListResponse mirrors API ToolListResponse.
type ToolListResponse struct {
	Items []ToolSummary `json:"items"`
}

// NamespaceListResponse mirrors API NamespaceListResponse.
type NamespaceListResponse struct {
	Namespaces []string `json:"namespaces"`
}

func getJSON(ctx context.Context, baseURL, path string, query url.Values, bearer string) ([]byte, int, error) {
	baseURL = strings.TrimRight(baseURL, "/")
	u, err := url.Parse(baseURL + path)
	if err != nil {
		return nil, 0, err
	}
	if query != nil {
		u.RawQuery = query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, 0, err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	req.Header.Set("Accept", "application/json")

	cli := &http.Client{Timeout: 60 * time.Second}
	res, err := tracedDo(req, cli)
	if err != nil {
		return nil, 0, err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, res.StatusCode, err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, res.StatusCode, fmt.Errorf("HTTP %d: %s", res.StatusCode, strings.TrimSpace(string(body)))
	}
	return body, res.StatusCode, nil
}

// ListNamespaces calls GET /api/v1/namespaces.
func ListNamespaces(ctx context.Context, baseURL, bearer string, enabledOnly bool) (*NamespaceListResponse, error) {
	q := url.Values{}
	if !enabledOnly {
		q.Set("enabled_only", "false")
	}
	body, _, err := getJSON(ctx, baseURL, "/api/v1/namespaces", q, bearer)
	if err != nil {
		return nil, err
	}
	var out NamespaceListResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode namespaces: %w", err)
	}
	return &out, nil
}

// ListAgents calls GET /api/v1/agents?namespace=
func ListAgents(ctx context.Context, baseURL, bearer, namespace string) (*AgentListResponse, error) {
	q := url.Values{}
	q.Set("namespace", namespace)
	body, _, err := getJSON(ctx, baseURL, "/api/v1/agents", q, bearer)
	if err != nil {
		return nil, err
	}
	var out AgentListResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode agents: %w", err)
	}
	return &out, nil
}

// ListTools calls GET /api/v1/tools?namespace=
func ListTools(ctx context.Context, baseURL, bearer, namespace string) (*ToolListResponse, error) {
	q := url.Values{}
	q.Set("namespace", namespace)
	body, _, err := getJSON(ctx, baseURL, "/api/v1/tools", q, bearer)
	if err != nil {
		return nil, err
	}
	var out ToolListResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode tools: %w", err)
	}
	return &out, nil
}

// GetAgent calls GET /api/v1/agents/{namespace}/{name}; returns raw JSON.
func GetAgent(ctx context.Context, baseURL, bearer, namespace, name string) ([]byte, error) {
	path := fmt.Sprintf("/api/v1/agents/%s/%s", url.PathEscape(namespace), url.PathEscape(name))
	body, _, err := getJSON(ctx, baseURL, path, nil, bearer)
	return body, err
}
