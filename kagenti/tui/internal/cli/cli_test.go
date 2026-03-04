package cli

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/kagenti/kagenti/kagenti/tui/internal/api"
)

// newTestServer returns an httptest.Server that handles the API routes used
// by the CLI commands and a CLIContext wired to it.
func newTestServer(t *testing.T) (*httptest.Server, *CLIContext) {
	t.Helper()

	mux := http.NewServeMux()

	// The API client uses:
	//   GET  /api/v1/agents?namespace=...     → list
	//   GET  /api/v1/agents/{ns}/{name}       → detail
	//   POST /api/v1/agents                   → create
	//   DELETE /api/v1/agents/{ns}/{name}      → delete
	// ServeMux routes "/api/v1/agents" (no trailing slash) only for exact match;
	// "/api/v1/agents/" catches sub-paths. Register both.
	agentHandler := func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/api/v1/agents")
		path = strings.TrimPrefix(path, "/")
		switch r.Method {
		case http.MethodGet:
			if path == "" {
				// list: GET /api/v1/agents?namespace=...
				json.NewEncoder(w).Encode(api.AgentListResponse{
					Items: []api.AgentSummary{
						{Name: "test-agent", Namespace: "team1", Status: "Running",
							Labels: api.ResourceLabels{Framework: "LangGraph", Protocol: "a2a"}},
					},
				})
			} else {
				// detail: GET /api/v1/agents/{ns}/{name}
				parts := strings.SplitN(path, "/", 2)
				name := parts[0]
				if len(parts) == 2 {
					name = parts[1]
				}
				json.NewEncoder(w).Encode(map[string]any{
					"metadata": map[string]any{"name": name, "namespace": "team1"},
				})
			}
		case http.MethodPost:
			var req api.CreateAgentRequest
			json.NewDecoder(r.Body).Decode(&req)
			json.NewEncoder(w).Encode(api.CreateAgentResponse{
				Success: true, Name: req.Name, Namespace: req.Namespace,
			})
		case http.MethodDelete:
			json.NewEncoder(w).Encode(api.DeleteResponse{Success: true, Message: "deleted"})
		}
	}
	mux.HandleFunc("/api/v1/agents", agentHandler)
	mux.HandleFunc("/api/v1/agents/", agentHandler)

	toolHandler := func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/api/v1/tools")
		path = strings.TrimPrefix(path, "/")
		switch r.Method {
		case http.MethodGet:
			if path == "" {
				json.NewEncoder(w).Encode(api.ToolListResponse{
					Items: []api.ToolSummary{
						{Name: "test-tool", Namespace: "team1", Status: "Running",
							Labels: api.ResourceLabels{Protocol: "sse"}, WorkloadType: "deployment"},
					},
				})
			} else {
				parts := strings.SplitN(path, "/", 2)
				name := parts[0]
				if len(parts) == 2 {
					name = parts[1]
				}
				json.NewEncoder(w).Encode(map[string]any{
					"metadata": map[string]any{"name": name, "namespace": "team1"},
				})
			}
		case http.MethodPost:
			var req api.CreateToolRequest
			json.NewDecoder(r.Body).Decode(&req)
			json.NewEncoder(w).Encode(api.CreateToolResponse{
				Success: true, Name: req.Name, Namespace: req.Namespace,
			})
		case http.MethodDelete:
			json.NewEncoder(w).Encode(api.DeleteResponse{Success: true, Message: "deleted"})
		}
	}
	mux.HandleFunc("/api/v1/tools", toolHandler)
	mux.HandleFunc("/api/v1/tools/", toolHandler)

	mux.HandleFunc("/api/v1/chat/", func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path
		if strings.HasSuffix(path, "/stream") {
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			flusher, _ := w.(http.Flusher)
			data, _ := json.Marshal(api.ChatStreamEvent{Content: "hello world", SessionID: "sess-123"})
			w.Write([]byte("data: " + string(data) + "\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			w.Write([]byte("data: [DONE]\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
		} else if strings.HasSuffix(path, "/send") {
			json.NewEncoder(w).Encode(api.ChatResponse{
				Content: "hello response", SessionID: "s1", IsComplete: true,
			})
		}
	})

	mux.HandleFunc("/api/v1/auth/status", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(api.AuthStatusResponse{
			Enabled: true, Authenticated: true,
		})
	})

	mux.HandleFunc("/api/v1/auth/me", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(api.UserInfoResponse{
			Username: "testuser", Authenticated: true,
		})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	client := api.NewClient(srv.URL, "test-token", "team1")
	ctx := &CLIContext{Client: client, Output: "table"}
	return srv, ctx
}

// captureStdout captures stdout during fn() and returns the output.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w

	fn()

	w.Close()
	os.Stdout = old

	var buf bytes.Buffer
	io.Copy(&buf, r)
	return buf.String()
}

// captureOutput captures both stdout and stderr during fn().
func captureOutput(t *testing.T, fn func()) (stdout, stderr string) {
	t.Helper()
	oldOut := os.Stdout
	oldErr := os.Stderr

	outR, outW, _ := os.Pipe()
	errR, errW, _ := os.Pipe()
	os.Stdout = outW
	os.Stderr = errW

	fn()

	outW.Close()
	errW.Close()
	os.Stdout = oldOut
	os.Stderr = oldErr

	var outBuf, errBuf bytes.Buffer
	io.Copy(&outBuf, outR)
	io.Copy(&errBuf, errR)
	return outBuf.String(), errBuf.String()
}

func TestAgentsListTable(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newAgentsCmd(ctx)
	cmd.SetArgs([]string{})
	// Attach --namespace flag via parent persistent flags
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("agents command failed: %v", err)
		}
	})

	if !strings.Contains(out, "test-agent") {
		t.Errorf("expected output to contain 'test-agent', got: %s", out)
	}
	if !strings.Contains(out, "LangGraph") {
		t.Errorf("expected output to contain 'LangGraph', got: %s", out)
	}
}

func TestAgentsListJSON(t *testing.T) {
	_, ctx := newTestServer(t)
	ctx.Output = "json"
	cmd := newAgentsCmd(ctx)
	cmd.SetArgs([]string{})
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("agents command failed: %v", err)
		}
	})

	var resp api.AgentListResponse
	if err := json.Unmarshal([]byte(out), &resp); err != nil {
		t.Fatalf("expected valid JSON, got: %s", out)
	}
	if len(resp.Items) != 1 || resp.Items[0].Name != "test-agent" {
		t.Errorf("unexpected JSON output: %s", out)
	}
}

func TestAgentDetail(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newAgentCmd(ctx)
	cmd.SetArgs([]string{"my-agent"})
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("agent command failed: %v", err)
		}
	})

	if !strings.Contains(out, "my-agent") {
		t.Errorf("expected output to contain 'my-agent', got: %s", out)
	}
}

func TestToolsListTable(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newToolsCmd(ctx)
	cmd.SetArgs([]string{})
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("tools command failed: %v", err)
		}
	})

	if !strings.Contains(out, "test-tool") {
		t.Errorf("expected output to contain 'test-tool', got: %s", out)
	}
}

func TestToolDetail(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newToolCmd(ctx)
	cmd.SetArgs([]string{"my-tool"})
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("tool command failed: %v", err)
		}
	})

	if !strings.Contains(out, "my-tool") {
		t.Errorf("expected output to contain 'my-tool', got: %s", out)
	}
}

func TestChatStreaming(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newChatCmd(ctx)
	cmd.SetArgs([]string{"my-agent", "-m", "hi"})
	cmd.Flags().String("namespace", "team1", "")

	stdout, stderr := captureOutput(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("chat command failed: %v", err)
		}
	})

	if !strings.Contains(stdout, "hello world") {
		t.Errorf("expected stdout to contain 'hello world', got: %s", stdout)
	}
	if !strings.Contains(stderr, "session-id: sess-123") {
		t.Errorf("expected stderr to contain session ID, got: %s", stderr)
	}
}

func TestDeployAgent(t *testing.T) {
	_, ctx := newTestServer(t)
	deployCmd := newDeployCmd(ctx)
	deployCmd.SetArgs([]string{"agent", "--name", "new-agent", "--container-image", "img:v1"})
	deployCmd.PersistentFlags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := deployCmd.Execute(); err != nil {
			t.Fatalf("deploy agent command failed: %v", err)
		}
	})

	if !strings.Contains(out, "new-agent") {
		t.Errorf("expected output to contain 'new-agent', got: %s", out)
	}
}

func TestDeployTool(t *testing.T) {
	_, ctx := newTestServer(t)
	deployCmd := newDeployCmd(ctx)
	deployCmd.SetArgs([]string{"tool", "--name", "new-tool", "--container-image", "img:v1"})
	deployCmd.PersistentFlags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := deployCmd.Execute(); err != nil {
			t.Fatalf("deploy tool command failed: %v", err)
		}
	})

	if !strings.Contains(out, "new-tool") {
		t.Errorf("expected output to contain 'new-tool', got: %s", out)
	}
}

func TestDeleteAgent(t *testing.T) {
	_, ctx := newTestServer(t)
	deleteCmd := newDeleteCmd(ctx)
	deleteCmd.SetArgs([]string{"agent", "old-agent", "-y"})
	deleteCmd.PersistentFlags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := deleteCmd.Execute(); err != nil {
			t.Fatalf("delete agent command failed: %v", err)
		}
	})

	if !strings.Contains(out, "old-agent") {
		t.Errorf("expected output to contain 'old-agent', got: %s", out)
	}
}

func TestDeleteTool(t *testing.T) {
	_, ctx := newTestServer(t)
	deleteCmd := newDeleteCmd(ctx)
	deleteCmd.SetArgs([]string{"tool", "old-tool", "-y"})
	deleteCmd.PersistentFlags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := deleteCmd.Execute(); err != nil {
			t.Fatalf("delete tool command failed: %v", err)
		}
	})

	if !strings.Contains(out, "old-tool") {
		t.Errorf("expected output to contain 'old-tool', got: %s", out)
	}
}

func TestDeleteAbort(t *testing.T) {
	orig := confirmDelete
	confirmDelete = func(kind, name string) bool { return false }
	defer func() { confirmDelete = orig }()

	_, ctx := newTestServer(t)
	deleteCmd := newDeleteCmd(ctx)
	deleteCmd.SetArgs([]string{"agent", "keep-me"})
	deleteCmd.PersistentFlags().String("namespace", "team1", "")

	_, stderr := captureOutput(t, func() {
		if err := deleteCmd.Execute(); err != nil {
			t.Fatalf("delete command failed: %v", err)
		}
	})

	if !strings.Contains(stderr, "Aborted") {
		t.Errorf("expected 'Aborted' on stderr, got: %s", stderr)
	}
}

func TestStatusTable(t *testing.T) {
	_, ctx := newTestServer(t)
	cmd := newStatusCmd(ctx)
	cmd.SetArgs([]string{})

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("status command failed: %v", err)
		}
	})

	if !strings.Contains(out, "Connected") {
		t.Errorf("expected output to contain 'Connected', got: %s", out)
	}
	if !strings.Contains(out, "testuser") {
		t.Errorf("expected output to contain 'testuser', got: %s", out)
	}
}

func TestStatusJSON(t *testing.T) {
	_, ctx := newTestServer(t)
	ctx.Output = "json"
	cmd := newStatusCmd(ctx)
	cmd.SetArgs([]string{})

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("status command failed: %v", err)
		}
	})

	var data map[string]any
	if err := json.Unmarshal([]byte(out), &data); err != nil {
		t.Fatalf("expected valid JSON, got: %s", out)
	}
	if data["connected"] != true {
		t.Errorf("expected connected=true, got: %v", data["connected"])
	}
}

func TestVersionCmd(t *testing.T) {
	// version command just prints and exits; test it doesn't error
	cmd := newVersionCmd()
	// We can't easily test os.Exit(0), so just verify the command exists
	if cmd.Use != "version" {
		t.Errorf("expected Use='version', got %q", cmd.Use)
	}
}

func TestRootCmdHelp(t *testing.T) {
	root := NewRootCmd()
	var buf bytes.Buffer
	root.SetOut(&buf)
	root.SetArgs([]string{"--help"})

	err := root.Execute()
	if err != nil {
		t.Fatalf("root --help failed: %v", err)
	}

	out := buf.String()
	for _, sub := range []string{"agents", "agent", "tools", "tool", "chat", "deploy", "delete", "login", "logout", "status", "version"} {
		if !strings.Contains(out, sub) {
			t.Errorf("expected help to contain subcommand %q", sub)
		}
	}
}

func TestToolsListWithArrayProtocol(t *testing.T) {
	// The backend may return protocol as a JSON array (e.g. ["a2a", "mcp"]).
	// Verify the full list-tools path handles this without error.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"items":[{"name":"multi-proto-tool","namespace":"team1","status":"Running","labels":{"protocol":["a2a","mcp"]},"workloadType":"deployment"}]}`))
	}))
	defer srv.Close()

	client := api.NewClient(srv.URL, "tok", "team1")
	ctx := &CLIContext{Client: client, Output: "table"}
	cmd := newToolsCmd(ctx)
	cmd.SetArgs([]string{})
	cmd.Flags().String("namespace", "team1", "")

	out := captureStdout(t, func() {
		if err := cmd.Execute(); err != nil {
			t.Fatalf("tools list failed: %v", err)
		}
	})

	if !strings.Contains(out, "multi-proto-tool") {
		t.Errorf("expected tool name in output, got: %s", out)
	}
	if !strings.Contains(out, "a2a, mcp") {
		t.Errorf("expected 'a2a, mcp' in output, got: %s", out)
	}
}

func TestOutputHelpers(t *testing.T) {
	// printTable
	out := captureStdout(t, func() {
		printTable([]string{"A", "B"}, [][]string{{"1", "2"}, {"3", "4"}})
	})
	if !strings.Contains(out, "A") || !strings.Contains(out, "4") {
		t.Errorf("printTable output unexpected: %s", out)
	}

	// printJSON
	out = captureStdout(t, func() {
		printJSON(map[string]string{"key": "val"})
	})
	if !strings.Contains(out, `"key"`) || !strings.Contains(out, `"val"`) {
		t.Errorf("printJSON output unexpected: %s", out)
	}
}
