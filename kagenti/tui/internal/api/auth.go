package api

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// GetAuthConfig fetches the auth configuration from the backend.
func (c *Client) GetAuthConfig() (*AuthConfigResponse, error) {
	u := c.apiURL("/auth/config")
	req, err := c.newRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	var resp AuthConfigResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetAuthStatus fetches the auth status from the backend.
func (c *Client) GetAuthStatus() (*AuthStatusResponse, error) {
	u := c.apiURL("/auth/status")
	req, err := c.newRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	var resp AuthStatusResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetCurrentUser fetches the current user info.
func (c *Client) GetCurrentUser() (*UserInfoResponse, error) {
	u := c.apiURL("/auth/me")
	req, err := c.newRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	var resp UserInfoResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetDashboardConfig fetches the dashboard configuration.
func (c *Client) GetDashboardConfig() (*DashboardConfigResponse, error) {
	u := c.apiURL("/config/dashboards")
	req, err := c.newRequest("GET", u, nil)
	if err != nil {
		return nil, err
	}
	var resp DashboardConfigResponse
	if err := c.do(req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// generatePKCE creates a PKCE code verifier and S256 challenge.
func generatePKCE() (verifier, challenge string, err error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", "", err
	}
	verifier = base64.RawURLEncoding.EncodeToString(buf)
	h := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(h[:])
	return verifier, challenge, nil
}

// RequestDeviceCode initiates the device code flow with Keycloak.
func (c *Client) RequestDeviceCode(keycloakURL, realm, clientID string) (*DeviceCodeResponse, error) {
	deviceURL := fmt.Sprintf("%s/realms/%s/protocol/openid-connect/auth/device", keycloakURL, realm)

	verifier, challenge, err := generatePKCE()
	if err != nil {
		return nil, fmt.Errorf("failed to generate PKCE: %w", err)
	}

	form := url.Values{}
	form.Set("client_id", clientID)
	form.Set("scope", "openid")
	form.Set("code_challenge_method", "S256")
	form.Set("code_challenge", challenge)

	req, err := http.NewRequest("POST", deviceURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("device code request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		if resp.StatusCode == http.StatusBadRequest {
			return nil, fmt.Errorf("device code request failed (HTTP 400): %s", string(body))
		}
		return nil, fmt.Errorf("device code request returned HTTP %d: %s", resp.StatusCode, string(body))
	}

	var dcr DeviceCodeResponse
	if err := json.NewDecoder(resp.Body).Decode(&dcr); err != nil {
		return nil, err
	}
	dcr.CodeVerifier = verifier
	return &dcr, nil
}

// PollDeviceToken polls Keycloak's token endpoint for device code completion.
// It blocks until the user authorizes, the code expires, or an error occurs.
func (c *Client) PollDeviceToken(keycloakURL, realm, clientID, deviceCode, codeVerifier string, interval int) (*TokenResponse, error) {
	tokenURL := fmt.Sprintf("%s/realms/%s/protocol/openid-connect/token", keycloakURL, realm)

	pollInterval := time.Duration(interval) * time.Second
	if pollInterval < 5*time.Second {
		pollInterval = 5 * time.Second
	}

	for {
		form := url.Values{}
		form.Set("grant_type", "urn:ietf:params:oauth:grant-type:device_code")
		form.Set("client_id", clientID)
		form.Set("device_code", deviceCode)
		form.Set("code_verifier", codeVerifier)

		req, err := http.NewRequest("POST", tokenURL, strings.NewReader(form.Encode()))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

		resp, err := c.HTTPClient.Do(req)
		if err != nil {
			return nil, fmt.Errorf("token poll failed: %w", err)
		}

		var tr TokenResponse
		if err := json.NewDecoder(resp.Body).Decode(&tr); err != nil {
			resp.Body.Close()
			return nil, err
		}
		resp.Body.Close()

		if tr.AccessToken != "" {
			return &tr, nil
		}

		switch tr.Error {
		case "authorization_pending":
			time.Sleep(pollInterval)
			continue
		case "slow_down":
			pollInterval += 5 * time.Second
			time.Sleep(pollInterval)
			continue
		case "expired_token":
			return nil, fmt.Errorf("device code expired")
		default:
			if tr.Error != "" {
				return nil, fmt.Errorf("auth error: %s - %s", tr.Error, tr.ErrorDesc)
			}
			return nil, fmt.Errorf("unexpected token response")
		}
	}
}
