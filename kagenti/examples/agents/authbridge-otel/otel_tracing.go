// Package main provides OTEL tracing extensions for the AuthBridge ext_proc.
//
// This file adds OpenTelemetry root span creation to the ext_proc gRPC server,
// enabling GenAI observability in MLflow/Phoenix without agent code changes.
//
// The ext_proc intercepts A2A JSON-RPC requests, creates root spans with
// all required attributes (MLflow, OpenInference, GenAI semantic conventions),
// and injects W3C Trace Context headers so agent auto-instrumented spans
// become children of the root span.
//
// This is a REFERENCE implementation for Approach A (issue #667).
// It shows the code that would be added to AuthProxy/go-processor/main.go.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
)

// agentOtelConfig holds agent metadata from ConfigMap/env vars.
type agentOtelConfig struct {
	AgentName    string
	AgentVersion string
	Provider     string
	ServiceName  string
}

// a2aRequest represents the relevant parts of an A2A JSON-RPC request.
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

// a2aResponse represents the relevant parts of an A2A JSON-RPC response.
type a2aResponse struct {
	Result struct {
		Artifacts []struct {
			Parts []struct {
				Text string `json:"text"`
			} `json:"parts"`
		} `json:"artifacts"`
	} `json:"result"`
}

var (
	agentConfig   agentOtelConfig
	tracerForSpan trace.Tracer
	textPropagator propagation.TextMapPropagator
)

// initOtelTracing initializes the OTEL tracing infrastructure.
// Call this at startup, after loadConfig().
func initOtelTracing() error {
	// Load agent config from env vars (injected from agent-otel-config ConfigMap)
	agentConfig = agentOtelConfig{
		AgentName:    getEnvOrDefault("AGENT_NAME", "weather-assistant"),
		AgentVersion: getEnvOrDefault("AGENT_VERSION", "1.0.0"),
		Provider:     getEnvOrDefault("AGENT_PROVIDER", "langchain"),
		ServiceName:  getEnvOrDefault("OTEL_SERVICE_NAME", "weather-service"),
	}

	otlpEndpoint := getEnvOrDefault(
		"OTEL_EXPORTER_OTLP_ENDPOINT",
		"http://otel-collector.kagenti-system.svc.cluster.local:8335",
	)

	log.Printf("[OTEL] Initializing tracing:")
	log.Printf("[OTEL]   Agent: %s v%s", agentConfig.AgentName, agentConfig.AgentVersion)
	log.Printf("[OTEL]   Provider: %s", agentConfig.Provider)
	log.Printf("[OTEL]   Service: %s", agentConfig.ServiceName)
	log.Printf("[OTEL]   OTLP Endpoint: %s", otlpEndpoint)

	// Create OTLP HTTP exporter
	ctx := context.Background()
	exporter, err := otlptracehttp.New(ctx,
		otlptracehttp.WithEndpoint(strings.TrimPrefix(
			strings.TrimPrefix(otlpEndpoint, "http://"),
			"https://",
		)),
		otlptracehttp.WithInsecure(),
	)
	if err != nil {
		return fmt.Errorf("failed to create OTLP exporter: %w", err)
	}

	// Create resource with service and agent attributes
	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(agentConfig.ServiceName),
			semconv.ServiceVersion(agentConfig.AgentVersion),
			attribute.String("gen_ai.agent.name", agentConfig.AgentName),
			attribute.String("gen_ai.agent.version", agentConfig.AgentVersion),
			attribute.String("gen_ai.system", agentConfig.Provider),
		),
	)
	if err != nil {
		return fmt.Errorf("failed to create resource: %w", err)
	}

	// Create tracer provider
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)

	// Set up W3C Trace Context propagation
	textPropagator = propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	)
	otel.SetTextMapPropagator(textPropagator)

	// Create tracer for root spans
	tracerForSpan = tp.Tracer("authbridge.otel.agent")

	log.Println("[OTEL] Tracing initialized successfully")
	return nil
}

// parseA2ARequest extracts user input and context from A2A JSON-RPC body.
func parseA2ARequest(body []byte) *a2aRequest {
	if len(body) == 0 {
		return nil
	}

	var req a2aRequest
	if err := json.Unmarshal(body, &req); err != nil {
		log.Printf("[OTEL] Failed to parse A2A request: %v", err)
		return nil
	}

	return &req
}

// parseA2AResponse extracts agent output from A2A JSON-RPC response body.
func parseA2AResponse(body []byte) string {
	if len(body) == 0 {
		return ""
	}

	var resp a2aResponse
	if err := json.Unmarshal(body, &resp); err != nil {
		log.Printf("[OTEL] Failed to parse A2A response: %v", err)
		return ""
	}

	if len(resp.Result.Artifacts) > 0 && len(resp.Result.Artifacts[0].Parts) > 0 {
		return resp.Result.Artifacts[0].Parts[0].Text
	}

	return ""
}

// startAgentRootSpan creates a new root span for an agent invocation.
// Returns the span and a context with the span attached.
// The caller must call span.End() when the request is complete.
func startAgentRootSpan(
	ctx context.Context,
	userInput string,
	conversationID string,
	userID string,
) (trace.Span, context.Context) {
	spanName := fmt.Sprintf("invoke_agent %s", agentConfig.AgentName)

	ctx, span := tracerForSpan.Start(ctx, spanName,
		trace.WithSpanKind(trace.SpanKindInternal),
	)

	// === GenAI Semantic Conventions ===
	span.SetAttributes(
		attribute.String("gen_ai.operation.name", "invoke_agent"),
		attribute.String("gen_ai.provider.name", agentConfig.Provider),
		attribute.String("gen_ai.agent.name", agentConfig.AgentName),
		attribute.String("gen_ai.agent.version", agentConfig.AgentVersion),
	)

	if userInput != "" {
		truncated := truncate(userInput, 1000)
		span.SetAttributes(
			attribute.String("gen_ai.prompt", truncated),
			attribute.String("input.value", truncated),
			attribute.String("mlflow.spanInputs", truncated),
		)
	}

	if conversationID != "" {
		span.SetAttributes(
			attribute.String("gen_ai.conversation.id", conversationID),
			attribute.String("mlflow.trace.session", conversationID),
			attribute.String("session.id", conversationID),
		)
	}

	// === MLflow Attributes ===
	span.SetAttributes(
		attribute.String("mlflow.spanType", "AGENT"),
		attribute.String("mlflow.traceName", agentConfig.AgentName),
		attribute.String("mlflow.runName", agentConfig.AgentName+"-invoke"),
		attribute.String("mlflow.source", agentConfig.ServiceName),
		attribute.String("mlflow.version", agentConfig.AgentVersion),
	)

	// User tracking from auth
	if userID != "" {
		span.SetAttributes(
			attribute.String("mlflow.user", userID),
			attribute.String("enduser.id", userID),
		)
	} else {
		span.SetAttributes(
			attribute.String("mlflow.user", "kagenti"),
			attribute.String("enduser.id", "kagenti"),
		)
	}

	// === OpenInference Attributes ===
	span.SetAttributes(
		attribute.String("openinference.span.kind", "AGENT"),
	)

	return span, ctx
}

// setSpanOutput sets response attributes on a span after the agent responds.
func setSpanOutput(span trace.Span, output string) {
	if output == "" {
		return
	}
	truncated := truncate(output, 1000)
	span.SetAttributes(
		attribute.String("gen_ai.completion", truncated),
		attribute.String("output.value", truncated),
		attribute.String("mlflow.spanOutputs", truncated),
	)
}

// injectTraceContext injects W3C Trace Context headers into the outgoing request.
// Returns the headers as a map for Envoy to add to the forwarded request.
func injectTraceContext(ctx context.Context) map[string]string {
	carrier := propagation.MapCarrier{}
	textPropagator.Inject(ctx, carrier)
	return carrier
}

// truncate truncates a string to the specified max length.
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen]
}

// getEnvOrDefault returns the environment variable value or a default.
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
