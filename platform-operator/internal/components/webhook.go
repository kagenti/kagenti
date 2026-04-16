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
	webhookName       = "webhook"
	webhookDeployment = "kagenti-webhook"
	webhookNamespace  = "kagenti-webhook-system"
)

// WebhookComponent manages the kagenti admission webhook deployment.
type WebhookComponent struct {
	client client.Client
}

// NewWebhookComponent creates a new WebhookComponent.
func NewWebhookComponent(c client.Client) *WebhookComponent {
	return &WebhookComponent{client: c}
}

func (c *WebhookComponent) Name() string {
	return webhookName
}

func (c *WebhookComponent) Enabled(spec *v1alpha1.KagentiPlatformSpec) bool {
	return spec.Webhook.ManagementState == v1alpha1.Managed
}

func (c *WebhookComponent) Install(ctx context.Context, platform *v1alpha1.KagentiPlatform) error {
	// TODO: Install kagenti-webhook via Helm SDK (kagenti-extensions chart).
	return nil
}

func (c *WebhookComponent) IsReady(ctx context.Context) (bool, string, error) {
	deploy := &appsv1.Deployment{}
	err := c.client.Get(ctx, types.NamespacedName{
		Name:      webhookDeployment,
		Namespace: webhookNamespace,
	}, deploy)
	if err != nil {
		return false, fmt.Sprintf("failed to get deployment: %v", err), nil
	}

	if deploy.Status.ReadyReplicas > 0 && deploy.Status.ReadyReplicas == *deploy.Spec.Replicas {
		return true, messageAllReplicasReady, nil
	}

	return false, fmt.Sprintf("ready %d/%d", deploy.Status.ReadyReplicas, *deploy.Spec.Replicas), nil
}

func (c *WebhookComponent) Uninstall(ctx context.Context) error {
	// TODO: Uninstall via Helm SDK.
	return nil
}
