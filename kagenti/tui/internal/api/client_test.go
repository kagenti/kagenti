package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// ---------- 401 Token Refresh Tests ----------

func TestDo_RefreshesTokenOn401(t *testing.T) {
	var callCount atomic.Int32

	// Keycloak token endpoint mock — always returns fresh tokens.
	keycloak := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(TokenResponse{
			AccessToken:  "refreshed-token",
			RefreshToken: "refreshed-refresh",
			TokenType:    "Bearer",
		})
	}))
	defer keycloak.Close()

	// API endpoint mock — returns 401 on first call, 200 on second.
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := callCount.Add(1)
		if n == 1 {
			w.WriteHeader(http.StatusUnauthorized)
			w.Write([]byte(`{"error":"token expired"}`))
			return
		}
		// Verify the retried request carries the refreshed token.
		if got := r.Header.Get("Authorization"); got != "Bearer refreshed-token" {
			t.Errorf("retry request should use refreshed token, got %q", got)
		}
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer api.Close()

	var refreshedAccess, refreshedRefresh string
	client := NewClient(api.URL, "expired-token", "team1")
	client.SetRefreshToken("old-refresh")
	client.SetKeycloakConfig(keycloak.URL, "test-realm", "test-client")
	client.OnTokenRefresh = func(access, refresh string) {
		refreshedAccess = access
		refreshedRefresh = refresh
	}

	req, _ := client.newRequest("GET", client.apiURL("/test"), nil)
	var result map[string]string
	err := client.do(req, &result)

	if err != nil {
		t.Fatalf("expected success after refresh, got: %v", err)
	}
	if result["status"] != "ok" {
		t.Errorf("expected status=ok, got %v", result)
	}
	if client.GetToken() != "refreshed-token" {
		t.Errorf("expected client token updated, got %q", client.GetToken())
	}
	if refreshedAccess != "refreshed-token" || refreshedRefresh != "refreshed-refresh" {
		t.Errorf("OnTokenRefresh not called correctly: access=%q refresh=%q", refreshedAccess, refreshedRefresh)
	}
	if callCount.Load() != 2 {
		t.Errorf("expected 2 API calls (original + retry), got %d", callCount.Load())
	}
}

func TestDo_RefreshFailureReturnsError(t *testing.T) {
	tests := []struct {
		name         string
		keycloakCode int
		keycloakBody TokenResponse
	}{
		{
			name:         "keycloak returns 400",
			keycloakCode: http.StatusBadRequest,
			keycloakBody: TokenResponse{Error: "invalid_grant", ErrorDesc: "token revoked"},
		},
		{
			name:         "keycloak returns 500",
			keycloakCode: http.StatusInternalServerError,
			keycloakBody: TokenResponse{},
		},
		{
			name:         "keycloak returns empty access token",
			keycloakCode: http.StatusOK,
			keycloakBody: TokenResponse{AccessToken: ""},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			keycloak := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.keycloakCode)
				json.NewEncoder(w).Encode(tc.keycloakBody)
			}))
			defer keycloak.Close()

			api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(http.StatusUnauthorized)
				w.Write([]byte(`{"error":"unauthorized"}`))
			}))
			defer api.Close()

			client := NewClient(api.URL, "expired", "team1")
			client.SetRefreshToken("some-refresh")
			client.SetKeycloakConfig(keycloak.URL, "realm", "client")

			req, _ := client.newRequest("GET", client.apiURL("/test"), nil)
			err := client.do(req, nil)
			if err == nil {
				t.Fatal("expected error when refresh fails, got nil")
			}
		})
	}
}

func TestDo_NoRefreshWithoutKeycloakConfig(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"unauthorized"}`))
	}))
	defer api.Close()

	// Client has no Keycloak config — should not attempt refresh.
	client := NewClient(api.URL, "expired", "team1")

	req, _ := client.newRequest("GET", client.apiURL("/test"), nil)
	err := client.do(req, nil)
	if err == nil {
		t.Fatal("expected error on 401 without refresh config")
	}
}

// ---------- SSE Stream Failure Tests ----------

func TestStreamChat_DroppedConnection(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(200)
		flusher, _ := w.(http.Flusher)

		// Send one event then close the connection abruptly.
		data, _ := json.Marshal(ChatStreamEvent{Content: "partial"})
		fmt.Fprintf(w, "data: %s\n\n", data)
		if flusher != nil {
			flusher.Flush()
		}
		// Server closes connection — simulates dropped connection.
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "", "team1")
	ch, err := client.StreamChat("team1", "agent", &ChatRequest{Message: "hi"})
	if err != nil {
		t.Fatalf("StreamChat should succeed initially: %v", err)
	}

	var gotContent bool
	var gotClosed bool
	for evt := range ch {
		if evt.Content == "partial" {
			gotContent = true
		}
		// Channel should eventually close without panic.
	}
	gotClosed = true

	if !gotContent {
		t.Error("expected to receive partial content before connection dropped")
	}
	if !gotClosed {
		t.Error("expected channel to close after dropped connection")
	}
}

func TestStreamChat_MalformedJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(200)
		flusher, _ := w.(http.Flusher)

		// Send malformed JSON data line.
		fmt.Fprintf(w, "data: {not valid json\n\n")
		if flusher != nil {
			flusher.Flush()
		}

		// Then send a valid event.
		data, _ := json.Marshal(ChatStreamEvent{Content: "valid"})
		fmt.Fprintf(w, "data: %s\n\n", data)
		if flusher != nil {
			flusher.Flush()
		}
		fmt.Fprintf(w, "data: [DONE]\n\n")
		if flusher != nil {
			flusher.Flush()
		}
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "", "team1")
	ch, err := client.StreamChat("team1", "agent", &ChatRequest{Message: "hi"})
	if err != nil {
		t.Fatalf("StreamChat should succeed: %v", err)
	}

	var gotValid, gotDone bool
	for evt := range ch {
		if evt.Content == "valid" {
			gotValid = true
		}
		if evt.Done {
			gotDone = true
		}
	}

	if !gotValid {
		t.Error("expected to receive valid event after malformed one")
	}
	if !gotDone {
		t.Error("expected to receive Done event")
	}
}

func TestStreamChat_HTTPError(t *testing.T) {
	tests := []struct {
		name   string
		code   int
		body   string
	}{
		{"500 Internal Server Error", 500, "internal error"},
		{"403 Forbidden", 403, "forbidden"},
		{"404 Not Found", 404, ""},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.code)
				if tc.body != "" {
					w.Write([]byte(tc.body))
				}
			}))
			defer srv.Close()

			client := NewClient(srv.URL, "", "team1")
			_, err := client.StreamChat("team1", "agent", &ChatRequest{Message: "hi"})
			if err == nil {
				t.Fatal("expected error for non-2xx response")
			}
		})
	}
}

// ---------- Timeout Tests ----------

func TestDo_TimeoutOnSlowResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Sleep longer than the client timeout.
		time.Sleep(2 * time.Second)
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "", "team1")
	// Set a very short timeout for the test.
	client.HTTPClient.Timeout = 100 * time.Millisecond

	req, _ := client.newRequest("GET", client.apiURL("/slow"), nil)
	err := client.do(req, nil)
	if err == nil {
		t.Fatal("expected timeout error, got nil")
	}
}

func TestDo_PostWithBody401Retry(t *testing.T) {
	// Verify that POST body is replayed correctly on 401 retry.
	var callCount atomic.Int32

	keycloak := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(TokenResponse{
			AccessToken:  "new-token",
			RefreshToken: "new-refresh",
		})
	}))
	defer keycloak.Close()

	var retryBody string
	apiSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := callCount.Add(1)
		if n == 1 {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		var req CreateAgentRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("failed to decode retry body: %v", err)
			w.WriteHeader(500)
			return
		}
		retryBody = req.Name
		json.NewEncoder(w).Encode(CreateAgentResponse{
			Success: true, Name: req.Name, Namespace: "team1",
		})
	}))
	defer apiSrv.Close()

	client := NewClient(apiSrv.URL, "expired", "team1")
	client.SetRefreshToken("r")
	client.SetKeycloakConfig(keycloak.URL, "realm", "client")

	resp, err := client.CreateAgent(&CreateAgentRequest{Name: "my-agent", Namespace: "team1"})
	if err != nil {
		t.Fatalf("expected success after retry, got: %v", err)
	}
	if !resp.Success || retryBody != "my-agent" {
		t.Errorf("expected replayed body with name=my-agent, got %q, success=%v", retryBody, resp.Success)
	}
}
