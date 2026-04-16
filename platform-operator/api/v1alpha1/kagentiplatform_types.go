/*
Copyright 2025-2026 IBM Corp.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ManagementState indicates how a component is managed by the platform operator.
// +kubebuilder:validation:Enum=Managed;Removed;Unmanaged
type ManagementState string

const (
	// Managed means the operator will install and reconcile the component.
	Managed ManagementState = "Managed"
	// Removed means the operator will ensure the component is not installed.
	Removed ManagementState = "Removed"
	// Unmanaged means the operator will not touch the component (user-managed).
	Unmanaged ManagementState = "Unmanaged"
)

// InfraRequirement indicates whether an infrastructure dependency is required.
// +kubebuilder:validation:Enum=Required;Optional;Ignored
type InfraRequirement string

const (
	// Required means the infrastructure must be present; the operator blocks if missing.
	Required InfraRequirement = "Required"
	// Optional means the operator checks for the dependency but does not block if absent.
	Optional InfraRequirement = "Optional"
	// Ignored means the operator skips validation for this dependency entirely.
	Ignored InfraRequirement = "Ignored"
)

// PlatformPhase describes the overall state of the platform installation.
// +kubebuilder:validation:Enum=Installing;Ready;Degraded;Blocked;Error
type PlatformPhase string

const (
	PhaseInstalling PlatformPhase = "Installing"
	PhaseReady      PlatformPhase = "Ready"
	PhaseDegraded   PlatformPhase = "Degraded"
	PhaseBlocked    PlatformPhase = "Blocked"
	PhaseError      PlatformPhase = "Error"
)

// DeletionPolicy controls what happens when the KagentiPlatform CR is deleted.
// +kubebuilder:validation:Enum=Delete;Retain
type DeletionPolicy string

const (
	// Delete removes all managed resources when the CR is deleted.
	DeletionPolicyDelete DeletionPolicy = "Delete"
	// Retain keeps managed resources when the CR is deleted.
	DeletionPolicyRetain DeletionPolicy = "Retain"
)

// ComponentSpec defines how a managed component should be configured.
type ComponentSpec struct {
	// ManagementState controls whether the operator manages this component.
	// +kubebuilder:default=Managed
	ManagementState ManagementState `json:"managementState,omitempty"`
}

// UISpec extends ComponentSpec with UI-specific settings.
type UISpec struct {
	ComponentSpec `json:",inline"`

	// Replicas sets the number of UI deployment replicas.
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`
}

// AuthSpec configures authentication for the platform.
type AuthSpec struct {
	// ManagementState controls whether the operator manages authentication.
	// +kubebuilder:default=Managed
	ManagementState ManagementState `json:"managementState,omitempty"`

	// OIDC configures the OpenID Connect provider for authentication.
	// +optional
	OIDC *OIDCSpec `json:"oidc,omitempty"`
}

// OIDCSpec defines the OIDC provider configuration.
type OIDCSpec struct {
	// IssuerURL is the OIDC provider's issuer URL.
	IssuerURL string `json:"issuerURL"`

	// ClientID is the OIDC client identifier.
	// +optional
	ClientID string `json:"clientID,omitempty"`

	// CredentialsSecretRef references a Secret containing OIDC client credentials.
	// The Secret must contain a 'client-secret' key.
	// +optional
	CredentialsSecretRef *SecretRef `json:"credentialsSecretRef,omitempty"`

	// RequiredScopes lists the OIDC scopes that must be requested.
	// +optional
	RequiredScopes []string `json:"requiredScopes,omitempty"`

	// RequiredClaims lists JWT claims that must be present in the token.
	// +optional
	RequiredClaims map[string]string `json:"requiredClaims,omitempty"`

	// Keycloak provides Keycloak-specific configuration when using the bundled Keycloak.
	// +optional
	Keycloak *KeycloakSpec `json:"keycloak,omitempty"`
}

// SecretRef references a Kubernetes Secret.
type SecretRef struct {
	// Name is the name of the Secret.
	Name string `json:"name"`

	// Namespace is the namespace of the Secret.
	// +optional
	Namespace string `json:"namespace,omitempty"`
}

// KeycloakSpec provides Keycloak-specific settings when using the bundled Keycloak instance.
type KeycloakSpec struct {
	// Realm is the Keycloak realm name.
	// +kubebuilder:default=kagenti
	// +optional
	Realm string `json:"realm,omitempty"`
}

// AgentNamespace defines an agent namespace to be created and configured.
type AgentNamespace struct {
	// Name is the namespace name.
	Name string `json:"name"`

	// Labels are additional labels to apply to the namespace.
	// +optional
	Labels map[string]string `json:"labels,omitempty"`
}

// InfrastructureSpec declares infrastructure dependencies and their requirement level.
type InfrastructureSpec struct {
	// CertManager specifies the cert-manager requirement.
	// +kubebuilder:default={requirement: Required}
	CertManager InfraComponentSpec `json:"certManager,omitempty"`

	// Istio specifies the Istio service mesh requirement.
	// +kubebuilder:default={requirement: Optional}
	Istio InfraComponentSpec `json:"istio,omitempty"`

	// SPIRE specifies the SPIFFE/SPIRE workload identity requirement.
	// +kubebuilder:default={requirement: Optional}
	SPIRE InfraComponentSpec `json:"spire,omitempty"`

	// Tekton specifies the Tekton pipelines requirement.
	// +kubebuilder:default={requirement: Required}
	Tekton InfraComponentSpec `json:"tekton,omitempty"`

	// Shipwright specifies the Shipwright build requirement.
	// +kubebuilder:default={requirement: Optional}
	Shipwright InfraComponentSpec `json:"shipwright,omitempty"`

	// GatewayAPI specifies the Gateway API requirement.
	// +kubebuilder:default={requirement: Required}
	GatewayAPI InfraComponentSpec `json:"gatewayApi,omitempty"`
}

// InfraComponentSpec defines the requirement level for an infrastructure dependency.
type InfraComponentSpec struct {
	// Requirement specifies whether this infrastructure dependency is required, optional, or ignored.
	// +kubebuilder:default=Required
	Requirement InfraRequirement `json:"requirement,omitempty"`
}

// ImageOverridesSpec allows overriding container images for components.
type ImageOverridesSpec struct {
	// AgentOperator overrides the agent operator image.
	// +optional
	AgentOperator string `json:"agentOperator,omitempty"`

	// Webhook overrides the webhook image.
	// +optional
	Webhook string `json:"webhook,omitempty"`

	// UIFrontend overrides the UI frontend image.
	// +optional
	UIFrontend string `json:"uiFrontend,omitempty"`

	// UIBackend overrides the UI backend image.
	// +optional
	UIBackend string `json:"uiBackend,omitempty"`
}

// KagentiPlatformSpec defines the desired state of KagentiPlatform.
type KagentiPlatformSpec struct {
	// AgentOperator configures the kagenti-operator component.
	// +kubebuilder:default={managementState: Managed}
	AgentOperator ComponentSpec `json:"agentOperator,omitempty"`

	// Webhook configures the admission webhook component.
	// +kubebuilder:default={managementState: Managed}
	Webhook ComponentSpec `json:"webhook,omitempty"`

	// UI configures the Kagenti UI (frontend + backend).
	// +kubebuilder:default={managementState: Managed}
	UI UISpec `json:"ui,omitempty"`

	// MCPGateway configures the MCP Gateway component.
	// +kubebuilder:default={managementState: Managed}
	MCPGateway ComponentSpec `json:"mcpGateway,omitempty"`

	// AgentNamespaces lists namespaces to create and configure for agent workloads.
	// +optional
	AgentNamespaces []AgentNamespace `json:"agentNamespaces,omitempty"`

	// Auth configures authentication for the platform.
	// +kubebuilder:default={managementState: Managed}
	Auth AuthSpec `json:"auth,omitempty"`

	// Infrastructure declares infrastructure dependencies and their requirement levels.
	// The operator validates (read-only) that required infrastructure is present.
	Infrastructure InfrastructureSpec `json:"infrastructure,omitempty"`

	// Domain is the base domain for the platform (used for ingress/routes).
	// +kubebuilder:default=localtest.me
	// +optional
	Domain string `json:"domain,omitempty"`

	// DeletionPolicy controls what happens to managed resources when the CR is deleted.
	// +kubebuilder:default=Delete
	// +optional
	DeletionPolicy DeletionPolicy `json:"deletionPolicy,omitempty"`

	// ImageOverrides allows overriding container images for all components.
	// +optional
	ImageOverrides *ImageOverridesSpec `json:"imageOverrides,omitempty"`
}

// ComponentStatusState describes the state of a single component.
// +kubebuilder:validation:Enum=Ready;Installing;Error;Removed
type ComponentStatusState string

const (
	ComponentReady      ComponentStatusState = "Ready"
	ComponentInstalling ComponentStatusState = "Installing"
	ComponentError      ComponentStatusState = "Error"
	ComponentRemoved    ComponentStatusState = "Removed"
)

// ComponentStatus describes the observed state of a managed component.
type ComponentStatus struct {
	// Status is the current state of the component.
	Status ComponentStatusState `json:"status"`

	// Message provides human-readable detail, especially on error.
	// +optional
	Message string `json:"message,omitempty"`

	// LastTransitionTime is the last time the status transitioned.
	// +optional
	LastTransitionTime metav1.Time `json:"lastTransitionTime,omitempty"`
}

// InfraComponentStatus describes the observed state of an infrastructure dependency.
type InfraComponentStatus struct {
	// Available indicates whether the infrastructure dependency was detected.
	Available bool `json:"available"`

	// Version is the detected version of the infrastructure component.
	// +optional
	Version string `json:"version,omitempty"`

	// Message provides human-readable detail.
	// +optional
	Message string `json:"message,omitempty"`
}

// ComponentsStatus groups the status of all managed components.
type ComponentsStatus struct {
	// AgentOperator status.
	AgentOperator ComponentStatus `json:"agentOperator,omitempty"`

	// Webhook status.
	Webhook ComponentStatus `json:"webhook,omitempty"`

	// UI status.
	UI ComponentStatus `json:"ui,omitempty"`

	// Auth status.
	Auth ComponentStatus `json:"auth,omitempty"`

	// MCPGateway status.
	// +optional
	MCPGateway ComponentStatus `json:"mcpGateway,omitempty"`
}

// InfrastructureStatus groups the observed state of infrastructure dependencies.
type InfrastructureStatus struct {
	// CertManager status.
	CertManager InfraComponentStatus `json:"certManager,omitempty"`

	// Istio status.
	Istio InfraComponentStatus `json:"istio,omitempty"`

	// SPIRE status.
	SPIRE InfraComponentStatus `json:"spire,omitempty"`

	// Tekton status.
	Tekton InfraComponentStatus `json:"tekton,omitempty"`

	// Shipwright status.
	Shipwright InfraComponentStatus `json:"shipwright,omitempty"`

	// GatewayAPI status.
	GatewayAPI InfraComponentStatus `json:"gatewayApi,omitempty"`
}

// EnvironmentStatus describes the detected cluster environment.
type EnvironmentStatus struct {
	// Platform is the detected platform type (e.g., "Kubernetes", "OpenShift").
	// +optional
	Platform string `json:"platform,omitempty"`

	// Version is the detected Kubernetes version.
	// +optional
	Version string `json:"version,omitempty"`
}

// KagentiPlatformStatus defines the observed state of KagentiPlatform.
type KagentiPlatformStatus struct {
	// Phase is the overall state of the platform installation.
	// +optional
	Phase PlatformPhase `json:"phase,omitempty"`

	// ObservedGeneration is the most recent generation observed by the controller.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// Environment describes the detected cluster environment.
	// +optional
	Environment *EnvironmentStatus `json:"environment,omitempty"`

	// Components reports the status of each managed component.
	// +optional
	Components *ComponentsStatus `json:"components,omitempty"`

	// Infrastructure reports the status of each infrastructure dependency.
	// +optional
	Infrastructure *InfrastructureStatus `json:"infrastructure,omitempty"`

	// Conditions represent the latest available observations of the platform's state.
	// Known condition types: InfrastructureReady, AgentOperatorReady, WebhookReady,
	// UIReady, AuthReady, Available, FullyOperational, MigrationRequired
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Cluster
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// KagentiPlatform is the Schema for the kagentiplatforms API.
// It is a cluster-scoped singleton that declares the desired state of a Kagenti platform installation.
type KagentiPlatform struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   KagentiPlatformSpec   `json:"spec,omitempty"`
	Status KagentiPlatformStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// KagentiPlatformList contains a list of KagentiPlatform.
type KagentiPlatformList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []KagentiPlatform `json:"items"`
}

func init() {
	SchemeBuilder.Register(&KagentiPlatform{}, &KagentiPlatformList{})
}
