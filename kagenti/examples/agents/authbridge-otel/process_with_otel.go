// Package main shows how the ext_proc Process() handler is extended for OTEL.
//
// This is a REFERENCE implementation showing the changes to
// AuthProxy/go-processor/main.go Process() method to support OTEL tracing.
//
// Key changes:
// 1. RequestBody handling: parse A2A JSON-RPC, create root span, inject traceparent
// 2. ResponseBody handling: parse response, set output attributes, end span
// 3. Per-stream span tracking using streamSpans map

package main

import (
	"context"
	"sync"

	core "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	v3 "github.com/envoyproxy/go-control-plane/envoy/service/ext_proc/v3"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
	grpccodes "google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// streamSpanState tracks the OTEL span for a single ext_proc stream (request lifecycle).
type streamSpanState struct {
	span trace.Span
	ctx  context.Context
}

// otelProcessor extends the base processor with OTEL span tracking.
type otelProcessor struct {
	v3.UnimplementedExternalProcessorServer
	// Per-stream span tracking. Each gRPC stream corresponds to one HTTP request.
	mu          sync.Mutex
	streamSpans map[v3.ExternalProcessor_ProcessServer]*streamSpanState
}

func newOtelProcessor() *otelProcessor {
	return &otelProcessor{
		streamSpans: make(map[v3.ExternalProcessor_ProcessServer]*streamSpanState),
	}
}

// ProcessWithOtel is the OTEL-enhanced version of Process().
// It handles RequestBody and ResponseBody in addition to headers.
func (p *otelProcessor) Process(stream v3.ExternalProcessor_ProcessServer) error {
	ctx := stream.Context()
	for {
		select {
		case <-ctx.Done():
			// Clean up span if stream ends unexpectedly
			p.cleanupSpan(stream)
			return ctx.Err()
		default:
		}

		req, err := stream.Recv()
		if err != nil {
			p.cleanupSpan(stream)
			return status.Errorf(grpccodes.Unknown, "cannot receive stream request: %v", err)
		}

		resp := &v3.ProcessingResponse{}

		switch r := req.Request.(type) {
		case *v3.ProcessingRequest_RequestHeaders:
			// Existing header handling (JWT validation, token exchange)
			headers := r.RequestHeaders.Headers
			direction := getHeaderValue(headers.Headers, "x-authbridge-direction")

			if direction == "inbound" {
				resp = handleInboundHeaders(headers)
			} else {
				resp = handleOutboundHeaders(headers)
			}

		case *v3.ProcessingRequest_RequestBody:
			// NEW: Parse A2A request body and create root span
			body := r.RequestBody.Body
			resp = p.handleRequestBody(stream, body)

		case *v3.ProcessingRequest_ResponseHeaders:
			// Pass through response headers
			resp = &v3.ProcessingResponse{
				Response: &v3.ProcessingResponse_ResponseHeaders{
					ResponseHeaders: &v3.HeadersResponse{},
				},
			}

		case *v3.ProcessingRequest_ResponseBody:
			// NEW: Parse A2A response body and set output on span
			body := r.ResponseBody.Body
			resp = p.handleResponseBody(stream, body)

		default:
			// Unknown request type, pass through
		}

		if err := stream.Send(resp); err != nil {
			p.cleanupSpan(stream)
			return status.Errorf(grpccodes.Unknown, "cannot send stream response: %v", err)
		}
	}
}

// handleRequestBody parses the A2A JSON-RPC request and creates a root span.
func (p *otelProcessor) handleRequestBody(
	stream v3.ExternalProcessor_ProcessServer,
	body []byte,
) *v3.ProcessingResponse {
	a2aReq := parseA2ARequest(body)
	if a2aReq == nil {
		// Not an A2A request, pass through
		return &v3.ProcessingResponse{
			Response: &v3.ProcessingResponse_RequestBody{
				RequestBody: &v3.BodyResponse{},
			},
		}
	}

	// Extract user input
	userInput := ""
	if len(a2aReq.Params.Message.Parts) > 0 {
		userInput = a2aReq.Params.Message.Parts[0].Text
	}

	// Extract conversation ID (try params.contextId, then message.contextId)
	conversationID := a2aReq.Params.ContextID
	if conversationID == "" {
		conversationID = a2aReq.Params.Message.ContextID
	}

	// Create root span
	ctx := context.Background()
	span, spanCtx := startAgentRootSpan(ctx, userInput, conversationID, "")

	// Store span for this stream
	p.mu.Lock()
	p.streamSpans[stream] = &streamSpanState{span: span, ctx: spanCtx}
	p.mu.Unlock()

	// Inject W3C Trace Context headers into the request going to the agent
	traceHeaders := injectTraceContext(spanCtx)

	// Build header mutations to add traceparent/tracestate
	var setHeaders []*core.HeaderValueOption
	for key, value := range traceHeaders {
		setHeaders = append(setHeaders, &core.HeaderValueOption{
			Header: &core.HeaderValue{
				Key:      key,
				RawValue: []byte(value),
			},
		})
	}

	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestBody{
			RequestBody: &v3.BodyResponse{
				Response: &v3.CommonResponse{
					HeaderMutation: &v3.HeaderMutation{
						SetHeaders: setHeaders,
					},
				},
			},
		},
	}
}

// handleResponseBody parses the A2A response and sets output attributes on the span.
func (p *otelProcessor) handleResponseBody(
	stream v3.ExternalProcessor_ProcessServer,
	body []byte,
) *v3.ProcessingResponse {
	// Get the span for this stream
	p.mu.Lock()
	state := p.streamSpans[stream]
	delete(p.streamSpans, stream)
	p.mu.Unlock()

	if state != nil && state.span != nil {
		// Parse A2A response for output
		output := parseA2AResponse(body)
		if output != "" {
			setSpanOutput(state.span, output)
		}

		// End the root span
		state.span.SetStatus(codes.Ok, "")
		state.span.End()
	}

	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_ResponseBody{
			ResponseBody: &v3.BodyResponse{},
		},
	}
}

// cleanupSpan ends any open span for a stream (on error/disconnect).
func (p *otelProcessor) cleanupSpan(stream v3.ExternalProcessor_ProcessServer) {
	p.mu.Lock()
	state := p.streamSpans[stream]
	delete(p.streamSpans, stream)
	p.mu.Unlock()

	if state != nil && state.span != nil {
		state.span.SetStatus(codes.Error, "stream ended unexpectedly")
		state.span.End()
	}
}

// handleInboundHeaders is a placeholder for the existing handleInbound logic.
// In the actual implementation, this would be the existing handleInbound method.
func handleInboundHeaders(headers *core.HeaderMap) *v3.ProcessingResponse {
	// Existing JWT validation logic from processor.handleInbound()
	// ... (see main.go)
	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestHeaders{
			RequestHeaders: &v3.HeadersResponse{},
		},
	}
}

// handleOutboundHeaders is a placeholder for the existing handleOutbound logic.
// In the actual implementation, this would be the existing handleOutbound method.
func handleOutboundHeaders(headers *core.HeaderMap) *v3.ProcessingResponse {
	// Existing token exchange logic from processor.handleOutbound()
	// ... (see main.go)
	return &v3.ProcessingResponse{
		Response: &v3.ProcessingResponse_RequestHeaders{
			RequestHeaders: &v3.HeadersResponse{},
		},
	}
}
