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

// AuthConfigResponse matches GET /api/v1/auth/config.
type AuthConfigResponse struct {
	Enabled     bool   `json:"enabled"`
	KeycloakURL string `json:"keycloak_url"`
	Realm       string `json:"realm"`
	ClientID    string `json:"client_id"`
	RedirectURI string `json:"redirect_uri"`
}

// FetchAuthConfig loads OIDC-related settings from the API (no auth required).
func FetchAuthConfig(ctx context.Context, backendBase string) (*AuthConfigResponse, error) {
	backendBase = strings.TrimRight(backendBase, "/")
	url := backendBase + "/api/v1/auth/config"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	cli := &http.Client{Timeout: 15 * time.Second}
	res, err := cli.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("GET auth/config: HTTP %d: %s", res.StatusCode, strings.TrimSpace(string(body)))
	}
	var ac AuthConfigResponse
	if err := json.Unmarshal(body, &ac); err != nil {
		return nil, fmt.Errorf("decode auth config: %w", err)
	}
	return &ac, nil
}
