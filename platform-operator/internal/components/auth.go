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

	"sigs.k8s.io/controller-runtime/pkg/client"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
)

const (
	authName = "auth"
)

// AuthComponent manages authentication configuration (Keycloak realm init or generic OIDC setup).
type AuthComponent struct {
	client client.Client
}

// NewAuthComponent creates a new AuthComponent.
func NewAuthComponent(c client.Client) *AuthComponent {
	return &AuthComponent{client: c}
}

func (c *AuthComponent) Name() string {
	return authName
}

func (c *AuthComponent) Enabled(spec *v1alpha1.KagentiPlatformSpec) bool {
	return spec.Auth.ManagementState == v1alpha1.Managed
}

func (c *AuthComponent) Install(ctx context.Context, platform *v1alpha1.KagentiPlatform) error {
	// TODO: Configure OIDC provider.
	// When Keycloak is specified, run realm init jobs and SPIFFE IdP setup.
	// When generic OIDC, configure OAuth secrets for UI, agent, API.
	return nil
}

func (c *AuthComponent) IsReady(ctx context.Context) (bool, string, error) {
	// TODO: Check that OAuth secrets exist and Keycloak realm (if applicable) is healthy.
	return true, "auth configured", nil
}

func (c *AuthComponent) Uninstall(ctx context.Context) error {
	// TODO: Remove OAuth secrets and auth configuration.
	return nil
}
