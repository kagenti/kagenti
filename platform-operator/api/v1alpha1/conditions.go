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

// Well-known condition types for KagentiPlatform.
const (
	// ConditionInfrastructureReady indicates all required infrastructure dependencies are present.
	ConditionInfrastructureReady = "InfrastructureReady"

	// ConditionAgentOperatorReady indicates the kagenti-operator component is ready.
	ConditionAgentOperatorReady = "AgentOperatorReady"

	// ConditionWebhookReady indicates the admission webhook is ready.
	ConditionWebhookReady = "WebhookReady"

	// ConditionUIReady indicates the UI (frontend + backend) is ready.
	ConditionUIReady = "UIReady"

	// ConditionAuthReady indicates authentication is configured and ready.
	ConditionAuthReady = "AuthReady"

	// ConditionAvailable indicates the platform is minimally functional.
	ConditionAvailable = "Available"

	// ConditionFullyOperational indicates all managed components are ready.
	ConditionFullyOperational = "FullyOperational"

	// ConditionMigrationRequired indicates an existing Ansible/Helm-managed install was detected
	// and must be adopted or removed before the operator can manage the platform.
	ConditionMigrationRequired = "MigrationRequired"
)

// Well-known condition reasons.
const (
	ReasonInstalling              = "Installing"
	ReasonReady                   = "Ready"
	ReasonComponentError          = "ComponentError"
	ReasonInfrastructureMissing   = "InfrastructureMissing"
	ReasonMigrationRequired       = "MigrationRequired"
	ReasonReconciling             = "Reconciling"
	ReasonComponentRemoved        = "ComponentRemoved"
)
