// OTEL-enhanced ext_proc for AuthBridge.
//
// This combines the original AuthBridge ext_proc (JWT validation + token exchange)
// with OpenTelemetry root span creation for GenAI observability.
//
// When processing inbound A2A requests, the ext_proc:
// 1. Parses the A2A JSON-RPC body to extract user input and context_id
// 2. Creates a root span "invoke_agent {name}" with MLflow/OpenInference/GenAI attributes
// 3. Injects W3C traceparent header so agent auto-instrumented spans become children
// 4. On response, captures output and sets gen_ai.completion on the root span
//
// Build: docker build -t authbridge-otel-processor .
// Run: OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:8335 ./go-processor

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	core "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	v3 "github.com/envoyproxy/go-control-plane/envoy/service/ext_proc/v3"
	typev3 "github.com/envoyproxy/go-control-plane/envoy/type/v3"
	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jwt"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	otelcodes "go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// ============================================================================
// Configuration
// ============================================================================

type Config struct {
	ClientID       string
	ClientSecret   string
	TokenURL       string
	TargetAudience string
	TargetScopes   string
	mu             sync.RWMutex
}

var globalConfig = &Config{}

type tokenExchangeResponse struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}

// OTEL agent config
var (
	agentName    string
	agentVersion string
	agentProvider string
	serviceName  string
	otelTracer   trace.Tracer
	textPropagator propagation.TextMapPropagator
	otelEnabled  bool
)

// JWT validation
var (
	jwksCache        *jwk.Cache
	inboundJWKSURL   string
	inboundIssuer    string
	expectedAudience string
)

// ============================================================================
// A2A JSON-RPC parsing
// ============================================================================

type a2aRequest struct {
	Method string `json:"method"`
	Params struct {
		ContextID string `json:"contextId"`
		Message   struct {
			MessageID string `json:"messageId"`
			ContextID string `json:"contextId"`
			Parts     []struct {
				Text string `json:"text"`
			} `json:"parts"`
		} `json:"message"`
	} `json:"params"`
}

type a2aResponse struct {
	Result struct {
		Artifacts []struct {
			Parts []struct {
				Text string `json:"text"`
			} `json:"parts"`
		} `json:"artifacts"`
	} `json:"result"`
}

// ============================================================================
// Config loading (from original ext_proc)
// ============================================================================

func readFileContent(path string) (string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(content)), nil
}

func loadConfig() {
	globalConfig.mu.Lock()
	defer globalConfig.mu.Unlock()

	globalConfig.TokenURL = os.Getenv("TOKEN_URL")
	globalConfig.TargetAudience = os.Getenv("TARGET_AUDIENCE")
	globalConfig.TargetScopes = os.Getenv("TARGET_SCOPES")

	clientIDFile := os.Getenv("CLIENT_ID_FILE")
	if clientIDFile == "" {
		clientIDFile = "/shared/client-id.txt"
	}
	clientSecretFile := os.Getenv("CLIENT_SECRET_FILE")
	if clientSecretFile == "" {
		clientSecretFile = "/shared/client-secret.txt"
	}

	if clientID, err := readFileContent(clientIDFile); err == nil && clientID != "" {
		globalConfig.ClientID = clientID
	} else if envClientID := os.Getenv("CLIENT_ID"); envClientID != "" {
		globalConfig.ClientID = envClientID
	}

	if clientSecret, err := readFileContent(clientSecretFile); err == nil && clientSecret != "" {
		globalConfig.ClientSecret = clientSecret
	} else if envClientSecret := os.Getenv("CLIENT_SECRET"); envClientSecret != "" {
		globalConfig.ClientSecret = envClientSecret
	}

	log.Printf("[Config] CLIENT_ID: %s, TOKEN_URL: %s", globalConfig.ClientID, globalConfig.TokenURL)
}

func waitForCredentials(maxWait time.Duration) bool {
	clientIDFile := os.Getenv("CLIENT_ID_FILE")
	if clientIDFile == "" {
		clientIDFile = "/shared/client-id.txt"
	}
	clientSecretFile := os.Getenv("CLIENT_SECRET_FILE")
	if clientSecretFile == "" {
		clientSecretFile = "/shared/client-secret.txt"
	}

	deadline := time.Now().Add(maxWait)
	for time.Now().Before(deadline) {
		clientID, err1 := readFileContent(clientIDFile)
		clientSecret, err2 := readFileContent(clientSecretFile)
		if err1 == nil && err2 == nil && clientID != "" && clientSecret != "" {
			log.Printf("[Config] Credential files are ready")
			return true
		}
		log.Printf("[Config] Credentials not ready yet, waiting...")
		time.Sleep(2 * time.Second)
	}
	return false
}

func getConfig() (clientID, clientSecret, tokenURL, targetAudience, targetScopes string) {
	globalConfig.mu.RLock()
	defer globalConfig.mu.RUnlock()
	return globalConfig.ClientID, globalConfig.ClientSecret, globalConfig.TokenURL, globalConfig.TargetAudience, globalConfig.TargetScopes
}

// ============================================================================
// JWT validation (from original ext_proc)
// ============================================================================

func deriveJWKSURL(tokenURL string) string {
	return strings.TrimSuffix(tokenURL, "/token") + "/certs"
}

func initJWKSCache(jwksURL string) {
	ctx := context.Background()
	jwksCache = jwk.NewCache(ctx)
	if err := jwksCache.Register(jwksURL); err != nil {
		log.Printf("[Inbound] Failed to register JWKS URL: %v", err)
		return
	}
	log.Printf("[Inbound] JWKS cache initialized: %s", jwksURL)
}

func validateInboundJWT(tokenString, jwksURL, expectedIss string) error {
	if jwksCache == nil {
		return fmt.Errorf("JWKS cache not initialized")
	}
	ctx := context.Background()
	keySet, err := jwksCache.Get(ctx, jwksURL)
	if err != nil {
		return fmt.Errorf("failed to fetch JWKS: %w", err)
	}
	token, err := jwt.Parse([]byte(tokenString), jwt.WithKeySet(keySet), jwt.WithValidate(true))
	if err != nil {
		return fmt.Errorf("failed to parse token: %w", err)
	}
	if token.Issuer() != expectedIss {
		return fmt.Errorf("invalid issuer: expected %s, got %s", expectedIss, token.Issuer())
	}
	if expectedAudience != "" {
		valid := false
		for _, aud := range token.Audience() {
			if aud == expectedAudience {
				valid = true
				break
			}
		}
		if !valid {
			return fmt.Errorf("invalid audience: expected %s, got %v", expectedAudience, token.Audience())
		}
	}
	return nil
}

func denyRequest(message string) *v3.ProcessingResponse {
	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_ImmediateResponse{
			ImmediateResponse: &v3.ImmediateResponse{
				Status: &typev3.HttpStatus{Code: typev3.StatusCode_Unauthorized},
				Body:   []byte(fmt.Sprintf(`{"error":"unauthorized","message":"%s"}`, message)),
			},
		},
	}
}

// Token exchange (from original ext_proc)
func exchangeToken(clientID, clientSecret, tokenURL, subjectToken, audience, scopes string) (string, error) {
	data := url.Values{}
	data.Set("client_id", clientID)
	data.Set("client_secret", clientSecret)
	data.Set("grant_type", "urn:ietf:params:oauth:grant-type:token-exchange")
	data.Set("requested_token_type", "urn:ietf:params:oauth:token-type:access_token")
	data.Set("subject_token", subjectToken)
	data.Set("subject_token_type", "urn:ietf:params:oauth:token-type:access_token")
	data.Set("audience", audience)
	data.Set("scope", scopes)

	resp, err := http.PostForm(tokenURL, data)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode != http.StatusOK {
		return "", status.Errorf(codes.Internal, "token exchange failed: %s", string(body))
	}
	var tokenResp tokenExchangeResponse
	if err := json.Unmarshal(body, &tokenResp); err != nil {
		return "", err
	}
	return tokenResp.AccessToken, nil
}

func getHeaderValue(headers []*core.HeaderValue, key string) string {
	for _, header := range headers {
		if strings.EqualFold(header.Key, key) {
			return string(header.RawValue)
		}
	}
	return ""
}

// ============================================================================
// OTEL tracing setup
// ============================================================================

func initOtelTracing() error {
	agentName = getEnvOrDefault("AGENT_NAME", "weather-assistant")
	agentVersion = getEnvOrDefault("AGENT_VERSION", "1.0.0")
	agentProvider = getEnvOrDefault("AGENT_PROVIDER", "langchain")
	serviceName = getEnvOrDefault("OTEL_SERVICE_NAME", "weather-service")
	otelEnabled = getEnvOrDefault("OTEL_TRACING_ENABLED", "true") == "true"

	if !otelEnabled {
		log.Println("[OTEL] Tracing disabled")
		return nil
	}

	otlpEndpoint := getEnvOrDefault(
		"OTEL_EXPORTER_OTLP_ENDPOINT",
		"http://otel-collector.kagenti-system.svc.cluster.local:8335",
	)

	log.Printf("[OTEL] Initializing: agent=%s service=%s endpoint=%s", agentName, serviceName, otlpEndpoint)

	ctx := context.Background()
	endpoint := strings.TrimPrefix(strings.TrimPrefix(otlpEndpoint, "http://"), "https://")
	exporter, err := otlptracehttp.New(ctx,
		otlptracehttp.WithEndpoint(endpoint),
		otlptracehttp.WithInsecure(),
	)
	if err != nil {
		return fmt.Errorf("failed to create OTLP exporter: %w", err)
	}

	res, err := resource.New(ctx, resource.WithAttributes(
		semconv.ServiceName(serviceName),
		semconv.ServiceVersion(agentVersion),
		attribute.String("gen_ai.agent.name", agentName),
		attribute.String("gen_ai.system", agentProvider),
	))
	if err != nil {
		return fmt.Errorf("failed to create resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)

	textPropagator = propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	)
	otel.SetTextMapPropagator(textPropagator)
	otelTracer = tp.Tracer("authbridge.otel.agent")

	log.Println("[OTEL] Tracing initialized")
	return nil
}

func getEnvOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// extractA2AOutput extracts agent output text from A2A response body.
// Handles both plain JSON-RPC responses and SSE-formatted streaming responses.
//
// SSE format: each event is "data: {json}\n\n"
// A2A JSON-RPC format: {"result":{"artifacts":[{"parts":[{"text":"..."}]}]}}
// A2A streaming event: {"result":{"type":"artifact-update","artifact":{"parts":[{"text":"..."}]}}}
func extractA2AOutput(body []byte) string {
	// Try plain JSON-RPC response first
	var resp a2aResponse
	if err := json.Unmarshal(body, &resp); err == nil {
		if len(resp.Result.Artifacts) > 0 && len(resp.Result.Artifacts[0].Parts) > 0 {
			return resp.Result.Artifacts[0].Parts[0].Text
		}
	}

	// SSE format: split by lines and find JSON data events
	bodyStr := string(body)
	lines := strings.Split(bodyStr, "\n")

	// Collect all text parts from SSE events (last one is typically the final answer)
	var lastOutput string
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		jsonStr := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if jsonStr == "" {
			continue
		}

		// Try to parse as JSON and extract text from various A2A event formats
		var event map[string]interface{}
		if err := json.Unmarshal([]byte(jsonStr), &event); err != nil {
			continue
		}

		// Check for result.artifacts[0].parts[0].text (final response)
		if result, ok := event["result"].(map[string]interface{}); ok {
			if artifacts, ok := result["artifacts"].([]interface{}); ok && len(artifacts) > 0 {
				if artifact, ok := artifacts[0].(map[string]interface{}); ok {
					if parts, ok := artifact["parts"].([]interface{}); ok && len(parts) > 0 {
						if part, ok := parts[0].(map[string]interface{}); ok {
							if text, ok := part["text"].(string); ok && text != "" {
								lastOutput = text
							}
						}
					}
				}
			}
			// Check for result.artifact.parts[0].text (streaming artifact-update)
			if artifact, ok := result["artifact"].(map[string]interface{}); ok {
				if parts, ok := artifact["parts"].([]interface{}); ok && len(parts) > 0 {
					if part, ok := parts[0].(map[string]interface{}); ok {
						if text, ok := part["text"].(string); ok && text != "" {
							lastOutput = text
						}
					}
				}
			}
		}
	}

	// If no SSE data found, try finding last JSON object in raw body
	if lastOutput == "" {
		lastBrace := strings.LastIndex(bodyStr, "}")
		if lastBrace >= 0 {
			depth := 0
			startIdx := -1
			for i := lastBrace; i >= 0; i-- {
				if bodyStr[i] == '}' {
					depth++
				} else if bodyStr[i] == '{' {
					depth--
					if depth == 0 {
						startIdx = i
						break
					}
				}
			}
			if startIdx >= 0 {
				var resp a2aResponse
				if err := json.Unmarshal([]byte(bodyStr[startIdx:lastBrace+1]), &resp); err == nil {
					if len(resp.Result.Artifacts) > 0 && len(resp.Result.Artifacts[0].Parts) > 0 {
						lastOutput = resp.Result.Artifacts[0].Parts[0].Text
					}
				}
			}
		}
	}

	return lastOutput
}

// ============================================================================
// OTEL-enhanced processor
// ============================================================================

type streamSpanState struct {
	span              trace.Span
	ctx               context.Context
	responseBody      []byte // accumulated response chunks for STREAMED mode
	childSpanIndex    int    // counter for nested child spans (LLM/tool events)
	taskID            string // A2A task ID for fire-and-forget result fetching
	hasOutput         bool   // whether output has been set on the root span
	completed         bool   // whether the main stream completed normally (end_of_stream)
	resubCancel       context.CancelFunc // cancel function for the resubscribe goroutine
}

type processor struct {
	v3.UnimplementedExternalProcessorServer
	mu          sync.Mutex
	streamSpans map[v3.ExternalProcessor_ProcessServer]*streamSpanState
}

// handleInbound processes inbound request HEADERS.
// Creates the OTEL root span HERE (before body) so the traceparent header
// is injected into the request BEFORE Envoy forwards headers to the agent.
// Body processing later enriches the span with input/output text.
func (p *processor) handleInbound(stream v3.ExternalProcessor_ProcessServer, headers *core.HeaderMap) *v3.ProcessingResponse {
	// JWT validation (if configured)
	if jwksCache != nil && inboundIssuer != "" {
		authHeader := getHeaderValue(headers.Headers, "authorization")
		if authHeader == "" {
			return denyRequest("missing Authorization header")
		}
		tokenString := strings.TrimPrefix(authHeader, "Bearer ")
		tokenString = strings.TrimPrefix(tokenString, "bearer ")
		if tokenString == authHeader {
			return denyRequest("invalid Authorization header format")
		}
		if err := validateInboundJWT(tokenString, inboundJWKSURL, inboundIssuer); err != nil {
			log.Printf("[Inbound] JWT validation failed: %v", err)
			return denyRequest(fmt.Sprintf("token validation failed: %v", err))
		}
	}

	// Build header mutations
	removeHeaders := []string{"x-authbridge-direction"}
	var setHeaders []*core.HeaderValueOption

	// Skip OTEL span creation for non-API paths (agent card, health)
	reqPath := getHeaderValue(headers.Headers, ":path")
	isAPIRequest := reqPath == "/" || strings.HasPrefix(reqPath, "/?")

	// Create OTEL root span NOW (during header processing) so traceparent
	// is injected BEFORE Envoy forwards headers to the agent.
	// Input/output will be set later during body processing.
	if otelEnabled && otelTracer != nil && isAPIRequest {
		spanName := fmt.Sprintf("invoke_agent %s", agentName)
		ctx, span := otelTracer.Start(context.Background(), spanName,
			trace.WithSpanKind(trace.SpanKindInternal),
		)

		// Set GenAI semantic convention attributes only.
		// MLflow/OpenInference attributes are derived by the OTEL Collector.
		span.SetAttributes(
			attribute.String("gen_ai.operation.name", "invoke_agent"),
			attribute.String("gen_ai.provider.name", agentProvider),
			attribute.String("gen_ai.agent.name", agentName),
			attribute.String("gen_ai.agent.version", agentVersion),
		)

		// Store span for body processing
		p.mu.Lock()
		p.streamSpans[stream] = &streamSpanState{span: span, ctx: ctx}
		p.mu.Unlock()

		// Inject traceparent header — THIS is the critical part.
		// The agent's OTEL SDK will read this header and create child spans
		// under our root span's trace context.
		carrier := propagation.MapCarrier{}
		textPropagator.Inject(ctx, carrier)
		for key, value := range carrier {
			setHeaders = append(setHeaders, &core.HeaderValueOption{
				Header: &core.HeaderValue{Key: key, RawValue: []byte(value)},
			})
		}

		log.Printf("[OTEL] Created root span at HEADER phase: %s (traceparent injected)", spanName)
	}

	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestHeaders{
			RequestHeaders: &v3.HeadersResponse{
				Response: &v3.CommonResponse{
					HeaderMutation: &v3.HeaderMutation{
						RemoveHeaders: removeHeaders,
						SetHeaders:    setHeaders,
					},
				},
			},
		},
	}
}

func (p *processor) handleOutbound(headers *core.HeaderMap) *v3.ProcessingResponse {
	clientID, clientSecret, tokenURL, targetAudience, targetScopes := getConfig()
	if clientID != "" && clientSecret != "" && tokenURL != "" && targetAudience != "" {
		authHeader := getHeaderValue(headers.Headers, "authorization")
		if authHeader != "" {
			subjectToken := strings.TrimPrefix(authHeader, "Bearer ")
			if subjectToken != authHeader {
				newToken, err := exchangeToken(clientID, clientSecret, tokenURL, subjectToken, targetAudience, targetScopes)
				if err == nil {
					return &v3.ProcessingResponse{
						Response: &v3.ProcessingResponse_RequestHeaders{
							RequestHeaders: &v3.HeadersResponse{
								Response: &v3.CommonResponse{
									HeaderMutation: &v3.HeaderMutation{
										SetHeaders: []*core.HeaderValueOption{{
											Header: &core.HeaderValue{
												Key: "authorization", RawValue: []byte("Bearer " + newToken),
											},
										}},
									},
								},
							},
						},
					}
				}
			}
		}
	}
	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestHeaders{
			RequestHeaders: &v3.HeadersResponse{},
		},
	}
}

// handleRequestBody enriches the existing root span with A2A request body data.
// The span was already created during header processing (handleInbound).
func (p *processor) handleRequestBody(stream v3.ExternalProcessor_ProcessServer, body []byte) *v3.ProcessingResponse {
	// Get the span created during header processing
	p.mu.Lock()
	state := p.streamSpans[stream]
	p.mu.Unlock()

	if state == nil || state.span == nil || !otelEnabled {
		return &v3.ProcessingResponse{
			Response: &v3.ProcessingResponse_RequestBody{
				RequestBody: &v3.BodyResponse{},
			},
		}
	}

	// Parse A2A JSON-RPC body to extract input and conversation ID
	var req a2aRequest
	if err := json.Unmarshal(body, &req); err != nil {
		log.Printf("[OTEL] Failed to parse A2A request body: %v", err)
		return &v3.ProcessingResponse{
			Response: &v3.ProcessingResponse_RequestBody{
				RequestBody: &v3.BodyResponse{},
			},
		}
	}

	userInput := ""
	if len(req.Params.Message.Parts) > 0 {
		userInput = req.Params.Message.Parts[0].Text
	}
	conversationID := req.Params.ContextID
	if conversationID == "" {
		conversationID = req.Params.Message.ContextID
	}

	// Enrich the root span with GenAI attributes only.
	// MLflow/OpenInference attributes are derived by the OTEL Collector.
	if userInput != "" {
		state.span.SetAttributes(
			attribute.String("gen_ai.prompt", userInput),
		)
	}
	if conversationID != "" {
		state.span.SetAttributes(
			attribute.String("gen_ai.conversation.id", conversationID),
			// MLflow requires mlflow.trace.session set by the producer, not by
			// collector transforms, for sessions to appear in the chat-sessions UI.
			attribute.String("mlflow.trace.session", conversationID),
		)
	}

	log.Printf("[OTEL] Enriched root span with body: input=%d chars, conversation=%s",
		len(userInput), conversationID)

	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestBody{
			RequestBody: &v3.BodyResponse{},
		},
	}
}

// parseSSEEvents extracts SSE data events from a chunk of response body.
// Each SSE event starts with "data: " and is followed by JSON.
func parseSSEEvents(chunk []byte) []string {
	var events []string
	lines := strings.Split(string(chunk), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "data:") {
			jsonStr := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if jsonStr != "" {
				events = append(events, jsonStr)
			}
		}
	}
	return events
}

// classifySSEEvent examines an A2A SSE event and returns its type and text content.
// Returns: eventType ("llm", "tool", "artifact", "status", ""), text content
func classifySSEEvent(jsonStr string) (string, string) {
	var event map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &event); err != nil {
		return "", ""
	}

	result, ok := event["result"].(map[string]interface{})
	if !ok {
		return "", ""
	}

	kind, _ := result["kind"].(string)

	switch kind {
	case "artifact-update":
		// Final answer artifact
		if artifact, ok := result["artifact"].(map[string]interface{}); ok {
			if parts, ok := artifact["parts"].([]interface{}); ok && len(parts) > 0 {
				if part, ok := parts[0].(map[string]interface{}); ok {
					if text, ok := part["text"].(string); ok {
						return "artifact", text
					}
				}
			}
		}
		return "artifact", ""

	case "status-update":
		// Check for agent step events in the status message
		if status, ok := result["status"].(map[string]interface{}); ok {
			if msg, ok := status["message"].(map[string]interface{}); ok {
				if parts, ok := msg["parts"].([]interface{}); ok && len(parts) > 0 {
					if part, ok := parts[0].(map[string]interface{}); ok {
						if text, ok := part["text"].(string); ok {
							// Detect LangGraph step events by key prefix
							// Events look like: "🚶‍♂️tools: ..." or "🚶‍♂️assistant: ..."
							if strings.Contains(text, "tools:") {
								return "tool", text
							}
							if strings.Contains(text, "assistant:") {
								return "llm", text
							}
						}
					}
				}
			}
		}
		// Final status (completed/failed) - no child span needed
		return "status", ""

	default:
		return "", ""
	}
}

// extractTaskIDAndContext extracts the A2A task ID and context ID from an SSE event.
// The first SSE event (kind=task) has: result.id = taskID, result.contextId = contextID
func extractTaskIDAndContext(jsonStr string) (string, string) {
	var event map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &event); err != nil {
		return "", ""
	}
	result, ok := event["result"].(map[string]interface{})
	if !ok {
		return "", ""
	}

	var taskID, contextID string

	// Extract contextId (present in all events)
	if cid, ok := result["contextId"].(string); ok {
		contextID = cid
	}

	kind, _ := result["kind"].(string)
	if kind == "task" {
		if id, ok := result["id"].(string); ok {
			taskID = id
		}
	}
	// Also check taskId field in status-update events
	if taskID == "" {
		if tid, ok := result["taskId"].(string); ok {
			taskID = tid
		}
	}

	return taskID, contextID
}

// resubscribeAndCapture opens a new SSE streaming connection to the agent's
// tasks/resubscribe endpoint and consumes events until a terminal state or
// the provided context is cancelled (which happens when the main stream
// completes normally and the resubscribe is no longer needed).
func resubscribeAndCapture(cancelCtx context.Context, taskID string, span trace.Span, spanCtx context.Context, startIndex int) (string, int) {
	reqBody := fmt.Sprintf(`{"jsonrpc":"2.0","id":"ext-proc-resub","method":"tasks/resubscribe","params":{"id":"%s"}}`, taskID)

	req, err := http.NewRequestWithContext(cancelCtx, "POST", "http://127.0.0.1:8000/", strings.NewReader(reqBody))
	if err != nil {
		log.Printf("[OTEL] resubscribe request creation failed: %v", err)
		return "", startIndex
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		if cancelCtx.Err() != nil {
			log.Printf("[OTEL] resubscribe cancelled (main stream completed normally)")
			return "", startIndex
		}
		log.Printf("[OTEL] resubscribe failed: %v", err)
		return "", startIndex
	}
	defer resp.Body.Close()

	// Read the SSE stream line by line
	var output string
	childIndex := startIndex
	buf := make([]byte, 0, 4096)
	readBuf := make([]byte, 1024)

	for {
		n, err := resp.Body.Read(readBuf)
		if n > 0 {
			buf = append(buf, readBuf[:n]...)

			// Process complete SSE events (terminated by \n\n)
			for {
				idx := strings.Index(string(buf), "\n\n")
				if idx < 0 {
					break
				}
				eventData := string(buf[:idx])
				buf = buf[idx+2:]

				for _, line := range strings.Split(eventData, "\n") {
					line = strings.TrimSpace(line)
					if !strings.HasPrefix(line, "data:") {
						continue
					}
					jsonStr := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
					if jsonStr == "" {
						continue
					}

					eventType, text := classifySSEEvent(jsonStr)
					switch eventType {
					case "llm", "tool":
						// Create child span
						if otelTracer != nil {
							childIndex++
							var spanName string
							var attrs []attribute.KeyValue
							if eventType == "llm" {
								spanName = "chat"
								attrs = []attribute.KeyValue{
									attribute.String("gen_ai.operation.name", "chat"),
									attribute.String("gen_ai.system", agentProvider),
								}
							} else {
								spanName = "execute_tool"
								attrs = []attribute.KeyValue{
									attribute.String("gen_ai.operation.name", "tool"),
								}
							}
							if text != "" {
								attrs = append(attrs, attribute.String("event.text", text))
							}
							attrs = append(attrs, attribute.Int("event.index", childIndex))
							_, childSpan := otelTracer.Start(spanCtx, spanName,
								trace.WithSpanKind(trace.SpanKindInternal),
								trace.WithAttributes(attrs...),
							)
							childSpan.SetStatus(otelcodes.Ok, "")
							childSpan.End()
							log.Printf("[OTEL] resubscribe: created child span %s (step %d)", spanName, childIndex)
						}
					case "artifact":
						if text != "" {
							output = text
							log.Printf("[OTEL] resubscribe: captured output (%d chars)", len(text))
						}
					case "status":
						// Check for terminal state
						var event map[string]interface{}
						if err := json.Unmarshal([]byte(jsonStr), &event); err == nil {
							if result, ok := event["result"].(map[string]interface{}); ok {
								if final, ok := result["final"].(bool); ok && final {
									log.Printf("[OTEL] resubscribe: stream completed (final=true)")
									return output, childIndex
								}
							}
						}
					}
				}
			}
		}
		if err != nil {
			if err != io.EOF {
				log.Printf("[OTEL] resubscribe read error: %v", err)
			}
			break
		}
	}

	// If resubscribe got no output (EventQueue closed before we connected),
	// fall back to tasks/get — the shielded agent execution saves the
	// completed task to the store even after SSE disconnect.
	if output == "" && cancelCtx.Err() == nil {
		log.Printf("[OTEL] resubscribe got no output, falling back to tasks/get")
		time.Sleep(3 * time.Second) // wait for shielded execution to finish
		output = fetchTaskResult(taskID)
		if output != "" {
			log.Printf("[OTEL] tasks/get recovered output (%d chars)", len(output))
		}
	}

	return output, childIndex
}

// fetchTaskResult queries tasks/get for the completed task result.
// Parses both plain JSON and SSE-formatted responses.
func fetchTaskResult(taskID string) string {
	reqBody := fmt.Sprintf(`{"jsonrpc":"2.0","id":"ext-proc-fetch","method":"tasks/get","params":{"id":"%s"}}`, taskID)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Post("http://127.0.0.1:8000/", "application/json", strings.NewReader(reqBody))
	if err != nil {
		log.Printf("[OTEL] tasks/get failed: %v", err)
		return ""
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return ""
	}

	// Parse SSE or plain JSON — look for artifact text
	return extractA2AOutput(body)
}

// extractGenAIAttrsFromJSON parses the event text as JSON to extract
// GenAI semantic convention attributes from LangChain message data.
// The text format is: "🚶‍♂️assistant: {JSON}" or "🚶‍♂️tools: {JSON}"
func extractGenAIAttrsFromJSON(text string, eventType string) (spanName string, attrs []attribute.KeyValue) {
	// Find the JSON part after the step prefix (e.g., "🚶‍♂️assistant: ")
	jsonStart := strings.Index(text, "{")
	if jsonStart < 0 {
		return "", nil
	}
	jsonStr := text[jsonStart:]

	var eventData struct {
		Messages []struct {
			Type             string                 `json:"type"`
			Content          string                 `json:"content"`
			Name             string                 `json:"name"`
			ToolCallID       string                 `json:"tool_call_id"`
			ResponseMetadata map[string]interface{} `json:"response_metadata"`
			ToolCalls        []struct {
				ID       string `json:"id"`
				Name     string `json:"name"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"messages"`
	}

	if err := json.Unmarshal([]byte(jsonStr), &eventData); err != nil {
		log.Printf("[OTEL] Could not parse event JSON: %v", err)
		return "", nil
	}

	if len(eventData.Messages) == 0 {
		return "", nil
	}

	switch eventType {
	case "llm":
		// Find the last AI message (has response_metadata with token usage)
		for i := len(eventData.Messages) - 1; i >= 0; i-- {
			msg := eventData.Messages[i]
			if msg.Type != "ai" {
				continue
			}

			if rm := msg.ResponseMetadata; rm != nil {
				// Extract token usage
				if tu, ok := rm["token_usage"].(map[string]interface{}); ok {
					if v, ok := tu["input_tokens"].(float64); ok {
						attrs = append(attrs, attribute.Int("gen_ai.usage.input_tokens", int(v)))
					} else if v, ok := tu["prompt_tokens"].(float64); ok {
						attrs = append(attrs, attribute.Int("gen_ai.usage.input_tokens", int(v)))
					}
					// Try both completion_tokens (OpenAI) and output_tokens
					if v, ok := tu["output_tokens"].(float64); ok {
						attrs = append(attrs, attribute.Int("gen_ai.usage.output_tokens", int(v)))
					} else if v, ok := tu["completion_tokens"].(float64); ok {
						attrs = append(attrs, attribute.Int("gen_ai.usage.output_tokens", int(v)))
					}
					if v, ok := tu["total_tokens"].(float64); ok {
						attrs = append(attrs, attribute.Int("gen_ai.usage.total_tokens", int(v)))
					}
				}

				// Extract model name
				var modelName string
				if model, ok := rm["model_name"].(string); ok && model != "" {
					modelName = model
					attrs = append(attrs, attribute.String("gen_ai.response.model", model))
					attrs = append(attrs, attribute.String("gen_ai.request.model", model))
				}

				// Extract finish reason
				if reason, ok := rm["finish_reason"].(string); ok && reason != "" {
					attrs = append(attrs, attribute.String("gen_ai.response.finish_reasons", reason))
				}

				// Set span name per GenAI spec: "chat {gen_ai.request.model}"
				if modelName != "" {
					spanName = fmt.Sprintf("chat %s", modelName)
				}
			}

			// Check if this is a tool-calling LLM step
			if len(msg.ToolCalls) > 0 {
				if spanName == "" {
					spanName = "chat"
				}
				// Add tool call names as context
				var toolNames []string
				for _, tc := range msg.ToolCalls {
					name := tc.Name
					if name == "" {
						name = tc.Function.Name
					}
					if name != "" {
						toolNames = append(toolNames, name)
					}
				}
				if len(toolNames) > 0 {
					attrs = append(attrs, attribute.String("gen_ai.tool.calls", strings.Join(toolNames, ",")))
				}
			} else if msg.Content != "" && spanName == "" {
				spanName = "chat"
			}
			break
		}

	case "tool":
		// Find tool messages
		for _, msg := range eventData.Messages {
			if msg.Type != "tool" {
				continue
			}
			if msg.Name != "" {
				spanName = fmt.Sprintf("execute_tool %s", msg.Name)
				attrs = append(attrs, attribute.String("gen_ai.tool.name", msg.Name))
			}
			if msg.ToolCallID != "" {
				attrs = append(attrs, attribute.String("gen_ai.tool.call.id", msg.ToolCallID))
			}
			break
		}
	}

	return spanName, attrs
}

// createChildSpan creates a nested child span under the root invoke_agent span
// for an LLM or tool event detected in the SSE stream. Parses the event JSON
// to extract GenAI semantic convention attributes.
func (p *processor) createChildSpan(state *streamSpanState, eventType string, text string) {
	if state == nil || state.span == nil || otelTracer == nil {
		return
	}

	state.childSpanIndex++
	idx := state.childSpanIndex

	// Extract GenAI attributes from the JSON event data
	spanName, genaiAttrs := extractGenAIAttrsFromJSON(text, eventType)

	// Fallback span names
	if spanName == "" {
		if eventType == "llm" {
			spanName = "chat"
		} else {
			spanName = "execute_tool"
		}
	}

	// Build attributes: GenAI standard + operation metadata
	var attrs []attribute.KeyValue
	if eventType == "llm" {
		attrs = append(attrs,
			attribute.String("gen_ai.operation.name", "chat"),
			attribute.String("gen_ai.system", agentProvider),
		)
	} else {
		attrs = append(attrs, attribute.String("gen_ai.operation.name", "tool"))
	}
	attrs = append(attrs, genaiAttrs...)
	attrs = append(attrs, attribute.Int("event.index", idx))

	// Create child span under the root span's context and immediately end it
	_, childSpan := otelTracer.Start(state.ctx, spanName,
		trace.WithSpanKind(trace.SpanKindInternal),
		trace.WithAttributes(attrs...),
	)
	childSpan.SetStatus(otelcodes.Ok, "")
	childSpan.End()
	log.Printf("[OTEL] Created child span: %s (step %d, %d attrs)", spanName, idx, len(attrs))
}

// handleResponseBody processes response chunks as they stream through.
// For each SSE chunk, it parses events and creates nested child spans for
// LLM and tool events. On end_of_stream, it sets the output on the root span.
func (p *processor) handleResponseBody(stream v3.ExternalProcessor_ProcessServer, body []byte, endOfStream bool) *v3.ProcessingResponse {
	p.mu.Lock()
	state := p.streamSpans[stream]

	if state != nil {
		// Accumulate response body chunks
		state.responseBody = append(state.responseBody, body...)

		// Parse SSE events from this chunk and create child spans
		if otelEnabled && len(body) > 0 {
			for _, jsonStr := range parseSSEEvents(body) {
				// Extract task ID and context ID from SSE events.
				// Context ID is set on the root span for session tracking.
				// Task ID is used for resubscribe on client disconnect.
				if state.taskID == "" {
					tid, cid := extractTaskIDAndContext(jsonStr)
					if cid != "" {
						state.span.SetAttributes(
							attribute.String("gen_ai.conversation.id", cid),
							attribute.String("mlflow.trace.session", cid),
						)
						log.Printf("[OTEL] Set conversation ID: %s", cid)
					}
					if tid != "" {
						state.taskID = tid
						log.Printf("[OTEL] Captured task ID: %s", tid)

						// Start background resubscribe immediately while stream is active.
						// If the main stream completes normally, we cancel this goroutine.
						// If the client disconnects, this goroutine captures remaining events.
						resubCtx, resubCancel := context.WithCancel(context.Background())
						state.resubCancel = resubCancel
						go func(ctx context.Context, taskID string, span trace.Span, spanCtx context.Context) {
							output, childCount := resubscribeAndCapture(ctx, taskID, span, spanCtx, 0)
							if ctx.Err() != nil {
								// Cancelled because main stream completed — do nothing
								return
							}
							// Main stream disconnected — this goroutine is the fallback
							if output != "" {
								t := output
								span.SetAttributes(
									attribute.String("gen_ai.completion", t),
								)
								span.SetStatus(otelcodes.Ok, "")
								log.Printf("[OTEL] resubscribe recovered output (%d chars, %d child spans)", len(output), childCount)
							} else {
								span.SetStatus(otelcodes.Ok, "client disconnected")
								log.Printf("[OTEL] resubscribe: no output (taskID=%s, %d child spans)", taskID, childCount)
							}
							span.End()
							log.Printf("[OTEL] resubscribe: root span ended")
						}(resubCtx, tid, state.span, state.ctx)
					}
				}

				eventType, text := classifySSEEvent(jsonStr)
				switch eventType {
				case "llm", "tool":
					p.createChildSpan(state, eventType, text)
				case "artifact":
					// Set output on root span immediately
					if text != "" {
						t := text
						state.span.SetAttributes(
							attribute.String("gen_ai.completion", t),
						)
						state.hasOutput = true
						log.Printf("[OTEL] Set output on root span (%d chars)", len(text))
					}
				}
			}
		}
	}

	if !endOfStream {
		// More chunks coming, don't end span yet
		p.mu.Unlock()
		return &v3.ProcessingResponse{
			Response: &v3.ProcessingResponse_ResponseBody{
				ResponseBody: &v3.BodyResponse{},
			},
		}
	}

	// End of stream — main stream completed normally
	delete(p.streamSpans, stream)
	p.mu.Unlock()

	if state != nil && state.span != nil {
		state.completed = true

		// Cancel the background resubscribe goroutine — not needed
		if state.resubCancel != nil {
			state.resubCancel()
			log.Printf("[OTEL] Cancelled background resubscribe (main stream completed)")
		}

		fullBody := state.responseBody

		// If output wasn't set from artifact events, try extracting from full body
		if state.span.IsRecording() {
			output := extractA2AOutput(fullBody)
			if output != "" {
				t := output
				state.span.SetAttributes(
					attribute.String("gen_ai.completion", t),
				)
				log.Printf("[OTEL] Set output on root span from full body (%d chars)", len(output))
			}
		}

		state.span.SetStatus(otelcodes.Ok, "")
		state.span.End()
		log.Printf("[OTEL] Root span ended (accumulated %d bytes, %d child spans)", len(fullBody), state.childSpanIndex)
	}

	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_ResponseBody{
			ResponseBody: &v3.BodyResponse{},
		},
	}
}

func (p *processor) cleanupSpan(stream v3.ExternalProcessor_ProcessServer) {
	p.mu.Lock()
	state := p.streamSpans[stream]
	delete(p.streamSpans, stream)
	p.mu.Unlock()
	if state == nil || state.span == nil {
		return
	}

	// If the resubscribe goroutine is running, let it handle span completion.
	// It was started when we first captured the task ID, and it's already
	// connected to the agent's task stream. It will capture remaining events
	// + output, then end the span.
	if state.taskID != "" && state.resubCancel != nil {
		log.Printf("[OTEL] Client disconnected — resubscribe goroutine will complete the trace (taskID=%s, %d child spans so far)", state.taskID, state.childSpanIndex)
		// Do NOT end the span here — the resubscribe goroutine owns it now
		return
	}

	// No resubscribe running — end span with whatever we have
	if state.hasOutput {
		state.span.SetStatus(otelcodes.Ok, "")
	} else {
		state.span.SetStatus(otelcodes.Ok, "client disconnected")
	}
	state.span.End()
	log.Printf("[OTEL] Stream disconnected, no resubscribe available (%d child spans)", state.childSpanIndex)
}

func (p *processor) Process(stream v3.ExternalProcessor_ProcessServer) error {
	ctx := stream.Context()
	for {
		select {
		case <-ctx.Done():
			p.cleanupSpan(stream)
			return ctx.Err()
		default:
		}

		req, err := stream.Recv()
		if err != nil {
			p.cleanupSpan(stream)
			return status.Errorf(codes.Unknown, "cannot receive stream request: %v", err)
		}

		resp := &v3.ProcessingResponse{}

		switch r := req.Request.(type) {
		case *v3.ProcessingRequest_RequestHeaders:
			headers := r.RequestHeaders.Headers
			direction := getHeaderValue(headers.Headers, "x-authbridge-direction")
			path := getHeaderValue(headers.Headers, ":path")
			log.Printf("[ext_proc] RequestHeaders: direction=%q path=%q", direction, path)
			// In our config, there's only one listener (inbound on 15124).
			// The x-authbridge-direction header is added by virtual_host config
			// AFTER ext_proc runs, so it's always empty here.
			// Treat all traffic as inbound (create root span + inject traceparent).
			// When outbound listener is added, use direction header to distinguish.
			if direction == "outbound" {
				resp = p.handleOutbound(headers)
			} else {
				// Default: inbound (includes direction="" and direction="inbound")
				resp = p.handleInbound(stream, headers)
			}

		case *v3.ProcessingRequest_RequestBody:
			log.Printf("[ext_proc] RequestBody: %d bytes", len(r.RequestBody.Body))
			resp = p.handleRequestBody(stream, r.RequestBody.Body)

		case *v3.ProcessingRequest_ResponseHeaders:
			log.Printf("[ext_proc] ResponseHeaders received")
			resp = &v3.ProcessingResponse{
				Response: &v3.ProcessingResponse_ResponseHeaders{
					ResponseHeaders: &v3.HeadersResponse{},
				},
			}

		case *v3.ProcessingRequest_ResponseBody:
			eos := r.ResponseBody.EndOfStream
			log.Printf("[ext_proc] ResponseBody: %d bytes (end_of_stream=%v)", len(r.ResponseBody.Body), eos)
			resp = p.handleResponseBody(stream, r.ResponseBody.Body, eos)

		default:
			log.Printf("[ext_proc] Unknown request type: %T", r)
		}

		if err := stream.Send(resp); err != nil {
			p.cleanupSpan(stream)
			return status.Errorf(codes.Unknown, "cannot send stream response: %v", err)
		}
	}
}

// ============================================================================
// Main
// ============================================================================

func main() {
	log.Println("=== OTEL-Enhanced Go External Processor Starting ===")

	waitForCredentials(60 * time.Second)
	loadConfig()

	// Initialize JWT validation
	_, _, tokenURL, _, _ := getConfig()
	inboundIssuer = os.Getenv("ISSUER")
	expectedAudience = os.Getenv("EXPECTED_AUDIENCE")
	if tokenURL != "" && inboundIssuer != "" {
		inboundJWKSURL = deriveJWKSURL(tokenURL)
		initJWKSCache(inboundJWKSURL)
		log.Printf("[Inbound] Issuer: %s", inboundIssuer)
	}

	// Initialize OTEL tracing
	if err := initOtelTracing(); err != nil {
		log.Printf("[OTEL] Failed to initialize tracing: %v", err)
		log.Println("[OTEL] Continuing without OTEL tracing")
	}

	// Start gRPC server
	port := ":9090"
	lis, err := net.Listen("tcp", port)
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	v3.RegisterExternalProcessorServer(grpcServer, &processor{
		streamSpans: make(map[v3.ExternalProcessor_ProcessServer]*streamSpanState),
	})

	log.Printf("Starting OTEL-enhanced ext_proc on %s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
