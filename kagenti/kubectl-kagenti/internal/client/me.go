// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// UserInfo matches GET /api/v1/auth/me.
type UserInfo struct {
	Username      string   `json:"username"`
	Email         *string  `json:"email"`
	Roles         []string `json:"roles"`
	Authenticated bool     `json:"authenticated"`
}

// GetMe calls GET {baseURL}/api/v1/auth/me with optional Bearer token.
func GetMe(baseURL, bearer string) (*UserInfo, int, error) {
	baseURL = strings.TrimRight(baseURL, "/")
	url := baseURL + "/api/v1/auth/me"
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
	if err != nil {
		return nil, 0, err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	req.Header.Set("Accept", "application/json")

	cli := &http.Client{Timeout: 30 * time.Second}
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
	var u UserInfo
	if err := json.Unmarshal(body, &u); err != nil {
		return nil, res.StatusCode, fmt.Errorf("decode JSON: %w", err)
	}
	return &u, res.StatusCode, nil
}
