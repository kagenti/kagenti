package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Client is the Kagenti backend HTTP client.
type Client struct {
	BaseURL    string
	Token      string
	Namespace  string
	HTTPClient *http.Client

	// Keycloak token refresh fields
	RefreshToken string
	KeycloakURL  string
	Realm        string
	ClientID     string

	// OnTokenRefresh is called when a token is refreshed so callers can persist it.
	OnTokenRefresh func(accessToken, refreshToken string)

	refreshMu sync.Mutex
}

// NewClient creates a new API client.
func NewClient(baseURL, token, namespace string) *Client {
	return &Client{
		BaseURL:   strings.TrimRight(baseURL, "/"),
		Token:     token,
		Namespace: namespace,
		HTTPClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// SetToken updates the auth token.
func (c *Client) SetToken(token string) {
	c.Token = token
}

// SetRefreshToken updates the refresh token.
func (c *Client) SetRefreshToken(token string) {
	c.RefreshToken = token
}

// SetKeycloakConfig stores the Keycloak connection info for token refresh.
func (c *Client) SetKeycloakConfig(keycloakURL, realm, clientID string) {
	c.KeycloakURL = keycloakURL
	c.Realm = realm
	c.ClientID = clientID
}

// SetNamespace updates the current namespace.
func (c *Client) SetNamespace(ns string) {
	c.Namespace = ns
}

// apiURL returns the full URL for an API path.
func (c *Client) apiURL(path string) string {
	return c.BaseURL + "/api/v1" + path
}

// newRequest creates a new HTTP request with auth headers.
func (c *Client) newRequest(method, url string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequest(method, url, body)
	if err != nil {
		return nil, err
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	req.Header.Set("Content-Type", "application/json")
	return req, nil
}

// do executes a request and decodes the JSON response.
// On 401 responses, it attempts to refresh the token and retry once.
func (c *Client) do(req *http.Request, result interface{}) error {
	// Read the request body so we can replay it on retry
	var bodyBytes []byte
	if req.Body != nil {
		var err error
		bodyBytes, err = io.ReadAll(req.Body)
		if err != nil {
			return fmt.Errorf("failed to read request body: %w", err)
		}
		req.Body = io.NopCloser(bytes.NewReader(bodyBytes))
	}

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	// On 401, try to refresh the token and retry
	if resp.StatusCode == http.StatusUnauthorized && c.canRefresh() {
		resp.Body.Close()
		if refreshErr := c.refreshAccessToken(); refreshErr == nil {
			// Rebuild request with new token
			var bodyReader io.Reader
			if bodyBytes != nil {
				bodyReader = bytes.NewReader(bodyBytes)
			}
			retryReq, err := c.newRequest(req.Method, req.URL.String(), bodyReader)
			if err != nil {
				return err
			}
			retryResp, err := c.HTTPClient.Do(retryReq)
			if err != nil {
				return fmt.Errorf("retry request failed: %w", err)
			}
			defer retryResp.Body.Close()

			if retryResp.StatusCode < 200 || retryResp.StatusCode >= 300 {
				body, _ := io.ReadAll(retryResp.Body)
				return fmt.Errorf("HTTP %d: %s", retryResp.StatusCode, string(body))
			}
			if result != nil {
				return json.NewDecoder(retryResp.Body).Decode(result)
			}
			return nil
		}
		// Refresh failed — return the original 401
		return fmt.Errorf("HTTP 401: token expired and refresh failed")
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	if result != nil {
		return json.NewDecoder(resp.Body).Decode(result)
	}
	return nil
}

// canRefresh returns true if we have the info needed to refresh the token.
func (c *Client) canRefresh() bool {
	return c.RefreshToken != "" && c.KeycloakURL != "" && c.Realm != "" && c.ClientID != ""
}

// refreshAccessToken uses the refresh token to get a new access token from Keycloak.
func (c *Client) refreshAccessToken() error {
	c.refreshMu.Lock()
	defer c.refreshMu.Unlock()

	tokenURL := fmt.Sprintf("%s/realms/%s/protocol/openid-connect/token", c.KeycloakURL, c.Realm)

	form := url.Values{}
	form.Set("grant_type", "refresh_token")
	form.Set("client_id", c.ClientID)
	form.Set("refresh_token", c.RefreshToken)

	req, err := http.NewRequest("POST", tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("token refresh request failed: %w", err)
	}
	defer resp.Body.Close()

	var tr TokenResponse
	if err := json.NewDecoder(resp.Body).Decode(&tr); err != nil {
		return err
	}

	if tr.AccessToken == "" {
		if tr.Error != "" {
			return fmt.Errorf("token refresh failed: %s - %s", tr.Error, tr.ErrorDesc)
		}
		return fmt.Errorf("token refresh returned empty access token")
	}

	c.Token = tr.AccessToken
	if tr.RefreshToken != "" {
		c.RefreshToken = tr.RefreshToken
	}

	// Notify caller so they can persist the new tokens
	if c.OnTokenRefresh != nil {
		c.OnTokenRefresh(c.Token, c.RefreshToken)
	}

	return nil
}
