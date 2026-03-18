// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package authoidc

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// BrowserLogin runs OAuth2 authorization code flow with PKCE; returns access_token.
func BrowserLogin(ctx context.Context, ep *Endpoints, localPort int) (accessToken string, err error) {
	if ep == nil || ep.AuthURL == "" || ep.TokenURL == "" || ep.ClientID == "" {
		return "", fmt.Errorf("incomplete OIDC endpoints")
	}
	if localPort <= 0 {
		localPort = 8250
	}
	verifier, challenge, err := pkce()
	if err != nil {
		return "", err
	}
	state, err := randomURLString(24)
	if err != nil {
		return "", err
	}
	redirectURI := fmt.Sprintf("http://127.0.0.1:%d/oauth/callback", localPort)
	listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", localPort))
	if err != nil {
		return "", fmt.Errorf("listen on 127.0.0.1:%d: %w (try KAGENTI_OIDC_LOCAL_PORT or free the port)", localPort, err)
	}
	defer listener.Close()

	codeCh := make(chan string, 1)
	errCh := make(chan error, 1)
	mux := http.NewServeMux()
	mux.HandleFunc("/oauth/callback", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("state") != state {
			errCh <- fmt.Errorf("invalid state parameter")
			http.Error(w, "invalid state", http.StatusBadRequest)
			return
		}
		code := r.URL.Query().Get("code")
		if code == "" {
			er := r.URL.Query().Get("error_description")
			if er == "" {
				er = r.URL.Query().Get("error")
			}
			errCh <- fmt.Errorf("authorization failed: %s", er)
			http.Error(w, er, http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = io.WriteString(w, `<!DOCTYPE html><html><body><p>Login successful. You can close this window and return to the terminal.</p></body></html>`)
		codeCh <- code
	})

	srv := &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = srv.Serve(listener) }()
	defer func() { _ = srv.Shutdown(context.Background()) }()

	authParams := url.Values{}
	authParams.Set("client_id", ep.ClientID)
	authParams.Set("redirect_uri", redirectURI)
	authParams.Set("response_type", "code")
	authParams.Set("scope", "openid")
	authParams.Set("state", state)
	authParams.Set("code_challenge", challenge)
	authParams.Set("code_challenge_method", "S256")
	authURL := ep.AuthURL
	if strings.Contains(authURL, "?") {
		authURL += "&" + authParams.Encode()
	} else {
		authURL += "?" + authParams.Encode()
	}

	if err := openBrowser(authURL); err != nil {
		return "", fmt.Errorf("open browser: %w", err)
	}

	select {
	case code := <-codeCh:
		return exchange(ctx, ep, code, redirectURI, verifier)
	case err := <-errCh:
		return "", err
	case <-time.After(5 * time.Minute):
		return "", fmt.Errorf("login timed out waiting for browser callback")
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

func exchange(ctx context.Context, ep *Endpoints, code, redirectURI, verifier string) (string, error) {
	form := url.Values{}
	form.Set("grant_type", "authorization_code")
	form.Set("code", code)
	form.Set("redirect_uri", redirectURI)
	form.Set("client_id", ep.ClientID)
	form.Set("code_verifier", verifier)
	if ep.ClientSecret != "" {
		form.Set("client_secret", ep.ClientSecret)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, ep.TokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	if err != nil {
		return "", err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return "", fmt.Errorf("token exchange HTTP %d: %s", res.StatusCode, strings.TrimSpace(string(body)))
	}
	var tok struct {
		AccessToken string `json:"access_token"`
		Error       string `json:"error"`
		Description string `json:"error_description"`
	}
	if err := json.Unmarshal(body, &tok); err != nil {
		return "", fmt.Errorf("decode token response: %w", err)
	}
	if tok.AccessToken == "" {
		msg := tok.Description
		if msg == "" {
			msg = tok.Error
		}
		return "", fmt.Errorf("no access_token in response: %s", msg)
	}
	return tok.AccessToken, nil
}

func pkce() (verifier string, challenge string, err error) {
	b := make([]byte, 32)
	if _, err = rand.Read(b); err != nil {
		return "", "", err
	}
	verifier = base64.RawURLEncoding.EncodeToString(b)
	h := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(h[:])
	return verifier, challenge, nil
}

func randomURLString(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b)[:n], nil
}

func openBrowser(u string) error {
	switch runtime.GOOS {
	case "darwin":
		return exec.Command("open", u).Start()
	case "windows":
		return exec.Command("rundll32", "url.dll,FileProtocolHandler", u).Start()
	default:
		return exec.Command("xdg-open", u).Start()
	}
}
