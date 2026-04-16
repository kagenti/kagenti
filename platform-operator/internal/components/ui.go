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
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
)

const (
	uiName              = "ui"
	uiBackendDeployment = "kagenti-backend"
	uiNamespace         = "kagenti-system"
)

// UIComponent manages the Kagenti UI (frontend + backend) deployment.
type UIComponent struct {
	client client.Client
}

// NewUIComponent creates a new UIComponent.
func NewUIComponent(c client.Client) *UIComponent {
	return &UIComponent{client: c}
}

func (c *UIComponent) Name() string {
	return uiName
}

func (c *UIComponent) Enabled(spec *v1alpha1.KagentiPlatformSpec) bool {
	return spec.UI.ManagementState == v1alpha1.Managed
}

func (c *UIComponent) Install(ctx context.Context, platform *v1alpha1.KagentiPlatform) error {
	// TODO: Deploy UI frontend + backend Deployments, Services, HTTPRoutes.
	return nil
}

func (c *UIComponent) IsReady(ctx context.Context) (bool, string, error) {
	deploy := &appsv1.Deployment{}
	err := c.client.Get(ctx, types.NamespacedName{
		Name:      uiBackendDeployment,
		Namespace: uiNamespace,
	}, deploy)
	if err != nil {
		return false, fmt.Sprintf("failed to get deployment: %v", err), nil
	}

	if deploy.Status.ReadyReplicas > 0 && deploy.Status.ReadyReplicas == *deploy.Spec.Replicas {
		return true, messageAllReplicasReady, nil
	}

	return false, fmt.Sprintf("ready %d/%d", deploy.Status.ReadyReplicas, *deploy.Spec.Replicas), nil
}

func (c *UIComponent) Uninstall(ctx context.Context) error {
	// TODO: Remove UI deployments.
	return nil
}
