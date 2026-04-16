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

package components

import (
	"context"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
)

const messageAllReplicasReady = "all replicas ready"

// Component defines the interface that all managed Kagenti components must implement.
// Each component represents a deployable unit (e.g., agent-operator, webhook, UI).
type Component interface {
	// Name returns the component's unique identifier.
	Name() string

	// Enabled returns true if the component should be installed based on the platform spec.
	Enabled(spec *v1alpha1.KagentiPlatformSpec) bool

	// Install deploys or updates the component to match the desired state.
	Install(ctx context.Context, platform *v1alpha1.KagentiPlatform) error

	// IsReady checks whether the component is healthy and operational.
	// Returns (ready, message, error) where message provides human-readable detail.
	IsReady(ctx context.Context) (bool, string, error)

	// Uninstall removes the component from the cluster.
	Uninstall(ctx context.Context) error
}

// Registry holds all known components in reconciliation order.
type Registry struct {
	components []Component
}

// NewRegistry creates a component registry with the given components.
// Components are reconciled in the order they are provided.
func NewRegistry(components ...Component) *Registry {
	return &Registry{components: components}
}

// All returns all registered components in reconciliation order.
func (r *Registry) All() []Component {
	return r.components
}
