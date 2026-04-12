// Package api provides a pure HTTP client for the Kagenti backend API.
package api

import (
	"encoding/json"
	"strings"
)

// FlexibleString accepts both a JSON string and a JSON array of strings.
// When unmarshaled from an array it joins elements with ", ".
type FlexibleString string

// UnmarshalJSON implements json.Unmarshaler.
func (f *FlexibleString) UnmarshalJSON(data []byte) error {
	// Try string first.
	var s string
	if err := json.Unmarshal(data, &s); err == nil {
		*f = FlexibleString(s)
		return nil
	}
	// Try array of strings.
	var arr []string
	if err := json.Unmarshal(data, &arr); err != nil {
		return err
	}
	*f = FlexibleString(strings.Join(arr, ", "))
	return nil
}

// String returns the underlying string value.
func (f FlexibleString) String() string {
	return string(f)
}

// ResourceLabels holds labels for agent/tool resources.
type ResourceLabels struct {
	Protocol  FlexibleString `json:"protocol,omitempty"`
	Framework string         `json:"framework,omitempty"`
	Type      string         `json:"type,omitempty"`
}

// AgentSummary is a summary of an agent.
type AgentSummary struct {
	Name         string         `json:"name"`
	Namespace    string         `json:"namespace"`
	Description  string         `json:"description"`
	Status       string         `json:"status"`
	Labels       ResourceLabels `json:"labels"`
	WorkloadType string         `json:"workloadType,omitempty"`
	CreatedAt    string         `json:"createdAt,omitempty"`
}

// AgentListResponse is the response for listing agents.
type AgentListResponse struct {
	Items []AgentSummary `json:"items"`
}

// ToolSummary is a summary of a tool.
type ToolSummary struct {
	Name         string         `json:"name"`
	Namespace    string         `json:"namespace"`
	Description  string         `json:"description"`
	Status       string         `json:"status"`
	Labels       ResourceLabels `json:"labels"`
	WorkloadType string         `json:"workloadType,omitempty"`
	CreatedAt    string         `json:"createdAt,omitempty"`
}

// ToolListResponse is the response for listing tools.
type ToolListResponse struct {
	Items []ToolSummary `json:"items"`
}

// NamespaceListResponse is the response for listing namespaces.
type NamespaceListResponse struct {
	Namespaces []string `json:"namespaces"`
}

// DeleteResponse is the response for delete operations.
type DeleteResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

// DashboardConfigResponse holds dashboard URLs.
type DashboardConfigResponse struct {
	Traces         string `json:"traces"`
	Network        string `json:"network"`
	MCPInspector   string `json:"mcpInspector"`
	MCPProxy       string `json:"mcpProxy"`
	KeycloakConsole string `json:"keycloakConsole"`
	DomainName     string `json:"domainName"`
}

// AuthConfigResponse is the auth configuration from the backend.
type AuthConfigResponse struct {
	Enabled     bool   `json:"enabled"`
	KeycloakURL string `json:"keycloak_url,omitempty"`
	Realm       string `json:"realm,omitempty"`
	ClientID    string `json:"client_id,omitempty"`
	RedirectURI string `json:"redirect_uri,omitempty"`
}

// AuthStatusResponse is the authentication status.
type AuthStatusResponse struct {
	Enabled       bool   `json:"enabled"`
	Authenticated bool   `json:"authenticated"`
	KeycloakURL   string `json:"keycloak_url,omitempty"`
	Realm         string `json:"realm,omitempty"`
	ClientID      string `json:"client_id,omitempty"`
}

// UserInfoResponse is the current user info.
type UserInfoResponse struct {
	Username      string   `json:"username"`
	Email         string   `json:"email,omitempty"`
	Roles         []string `json:"roles"`
	Authenticated bool     `json:"authenticated"`
}

// AgentCardResponse is the A2A agent card.
type AgentCardResponse struct {
	Name        string                   `json:"name"`
	Description string                   `json:"description,omitempty"`
	Version     string                   `json:"version"`
	URL         string                   `json:"url"`
	Streaming   bool                     `json:"streaming"`
	Skills      []map[string]interface{} `json:"skills"`
}

// ChatRequest is the request to send a chat message.
type ChatRequest struct {
	Message   string `json:"message"`
	SessionID string `json:"session_id,omitempty"`
}

// ChatResponse is a non-streaming chat response.
type ChatResponse struct {
	Content    string `json:"content"`
	SessionID  string `json:"session_id"`
	IsComplete bool   `json:"is_complete"`
}

// ChatStreamEvent is a parsed SSE event from the streaming chat.
type ChatStreamEvent struct {
	Content   string                 `json:"content,omitempty"`
	SessionID string                 `json:"session_id,omitempty"`
	Done      bool                   `json:"done,omitempty"`
	Error     string                 `json:"error,omitempty"`
	Event     map[string]interface{} `json:"event,omitempty"`
	Debug     string                 `json:"-"` // internal debug trace, not from JSON
}

// SecretKeyRef references a key in a Kubernetes Secret.
type SecretKeyRef struct {
	Name string `json:"name"`
	Key  string `json:"key"`
}

// ConfigMapKeyRef references a key in a Kubernetes ConfigMap.
type ConfigMapKeyRef struct {
	Name string `json:"name"`
	Key  string `json:"key"`
}

// EnvVarSource selects a value from a Secret or ConfigMap.
type EnvVarSource struct {
	SecretKeyRef    *SecretKeyRef    `json:"secretKeyRef,omitempty"`
	ConfigMapKeyRef *ConfigMapKeyRef `json:"configMapKeyRef,omitempty"`
}

// EnvVar is an environment variable for agent/tool creation.
// Either Value or ValueFrom should be set, not both.
type EnvVar struct {
	Name      string        `json:"name"`
	Value     string        `json:"value,omitempty"`
	ValueFrom *EnvVarSource `json:"valueFrom,omitempty"`
}

// ServicePort is a service port configuration.
type ServicePort struct {
	Name       string `json:"name"`
	Port       int    `json:"port"`
	TargetPort int    `json:"targetPort"`
	Protocol   string `json:"protocol"`
}

// CreateAgentRequest is the request to create an agent.
type CreateAgentRequest struct {
	Name             string        `json:"name"`
	Namespace        string        `json:"namespace"`
	Protocol         string        `json:"protocol"`
	Framework        string        `json:"framework"`
	DeploymentMethod string        `json:"deploymentMethod"`
	WorkloadType     string        `json:"workloadType"`
	EnvVars          []EnvVar      `json:"envVars,omitempty"`
	GitURL           string        `json:"gitUrl,omitempty"`
	GitPath          string        `json:"gitPath,omitempty"`
	GitBranch        string        `json:"gitBranch,omitempty"`
	ImageTag         string        `json:"imageTag,omitempty"`
	ContainerImage   string        `json:"containerImage,omitempty"`
	ImagePullSecret  string        `json:"imagePullSecret,omitempty"`
	ServicePorts     []ServicePort `json:"servicePorts,omitempty"`
	CreateHTTPRoute  bool          `json:"createHttpRoute"`
	AuthBridgeEnabled bool         `json:"authBridgeEnabled"`
	SpireEnabled     bool          `json:"spireEnabled"`
	EnvoyProxyInject          *bool `json:"envoyProxyInject,omitempty"`
	SpiffeHelperInject        *bool `json:"spiffeHelperInject,omitempty"`
	ClientRegistrationInject  *bool `json:"clientRegistrationInject,omitempty"`
}

// CreateAgentResponse is the response after creating an agent.
type CreateAgentResponse struct {
	Success   bool   `json:"success"`
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Message   string `json:"message"`
}

// CreateToolRequest is the request to create a tool.
type CreateToolRequest struct {
	Name             string        `json:"name"`
	Namespace        string        `json:"namespace"`
	Protocol         string        `json:"protocol"`
	Framework        string        `json:"framework"`
	Description      string        `json:"description,omitempty"`
	DeploymentMethod string        `json:"deploymentMethod"`
	WorkloadType     string        `json:"workloadType"`
	EnvVars          []EnvVar      `json:"envVars,omitempty"`
	ContainerImage   string        `json:"containerImage,omitempty"`
	ImagePullSecret  string        `json:"imagePullSecret,omitempty"`
	GitURL           string        `json:"gitUrl,omitempty"`
	GitRevision      string        `json:"gitRevision,omitempty"`
	ContextDir       string        `json:"contextDir,omitempty"`
	ImageTag         string        `json:"imageTag,omitempty"`
	ServicePorts     []ServicePort `json:"servicePorts,omitempty"`
	CreateHTTPRoute  bool          `json:"createHttpRoute"`
	AuthBridgeEnabled bool         `json:"authBridgeEnabled"`
	SpireEnabled     bool          `json:"spireEnabled"`
	EnvoyProxyInject          *bool `json:"envoyProxyInject,omitempty"`
	SpiffeHelperInject        *bool `json:"spiffeHelperInject,omitempty"`
	ClientRegistrationInject  *bool `json:"clientRegistrationInject,omitempty"`
}

// CreateToolResponse is the response after creating a tool.
type CreateToolResponse struct {
	Success   bool   `json:"success"`
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Message   string `json:"message"`
}

// DeviceCodeResponse is the Keycloak device code grant response.
type DeviceCodeResponse struct {
	DeviceCode              string `json:"device_code"`
	UserCode                string `json:"user_code"`
	VerificationURI         string `json:"verification_uri"`
	VerificationURIComplete string `json:"verification_uri_complete"`
	ExpiresIn               int    `json:"expires_in"`
	Interval                int    `json:"interval"`
	CodeVerifier            string `json:"-"` // PKCE code verifier (not from JSON)
}

// TokenResponse is the Keycloak token endpoint response.
type TokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token,omitempty"`
	TokenType    string `json:"token_type"`
	ExpiresIn    int    `json:"expires_in"`
	Error        string `json:"error,omitempty"`
	ErrorDesc    string `json:"error_description,omitempty"`
}
